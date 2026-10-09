from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_intents import (
    ExpenseDecision,
    format_brl,
    is_manual_expense_candidate,
    parse_manual_expense,
    suggest_expense_category_name,
)
from app.ai_pricing import estimated_cost
from app.ai_provider import AIProvider, AIProviderError, FunctionCall, ProviderRequest
from app.ai_tools import (
    ToolResult,
    audit_summary,
    execute_finance_tool,
    sanitize_for_provider,
    tool_schemas,
)
from app.config import settings
from app.finance_engine import current_financial_date, financial_day_after, financial_day_start
from app.models import (
    Account,
    AIConversation,
    AIMemory,
    AIMessage,
    AIToolCall,
    Category,
    Transaction,
    User,
)

MAX_TOOL_ROUNDS = 5
CONTEXT_MESSAGE_LIMIT = 24
FINANCIAL_ZONE = ZoneInfo("America/Sao_Paulo")
PROMPT_PATH = Path(__file__).parent / "prompts" / "assistant_v1.md"
LOCAL_EXPENSE_MODEL = "local-expense-parser-v1"
PENDING_EXPENSE_CLARIFICATION_TYPE = "pending_expense_clarification"


def sse_event(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def choose_model(content: str) -> str:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFD", content.casefold())
        if unicodedata.category(char) != "Mn"
    )
    complex_queries = (
        "comparar",
        "compare",
        "comparacao",
        "comparando",
        "comparativo",
        "diferenca entre periodos",
        "o que mudou nos meus gastos",
        "como mudaram meus gastos",
        "evolucao dos gastos",
        "tendencia de gastos",
        "tendencia dos ultimos",
        "analise detalhada",
        "analisar detalhadamente",
        "analise completa",
        "analise financeira",
        "analise dos meus gastos",
        "padroes de gasto",
        "varios periodos",
        "ultimos meses",
        "ultimos tres meses",
        "ultimos 3 meses",
        "planejar",
        "planejamento",
        "plano financeiro",
        "explique em detalhes",
        "explicacao detalhada",
    )
    return (
        settings.ai_model_smart
        if any(term in normalized for term in complex_queries)
        else settings.ai_model_fast
    )


def _safe_text_for_provider(content: str) -> str:
    redacted = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b", "[CPF ocultado]", content)
    redacted = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "[e-mail ocultado]", redacted)
    return re.sub(r"(?<!\w)\d{8,}(?!\w)", "[número longo ocultado]", redacted)


def _tool_history_items(message: AIMessage) -> list[dict[str, object]]:
    structured = message.structured_content
    if not isinstance(structured, dict):
        return []
    call_id = structured.get("call_id")
    name = structured.get("name")
    arguments = structured.get("arguments")
    output = structured.get("output")
    if not isinstance(call_id, str) or not isinstance(name, str) or not isinstance(output, dict):
        return []
    if isinstance(arguments, dict):
        args = json.dumps(sanitize_for_provider(arguments), ensure_ascii=False)
    elif isinstance(arguments, str):
        try:
            parsed: object = json.loads(arguments)
            safe_arguments = sanitize_for_provider(parsed)
            args = json.dumps(safe_arguments, ensure_ascii=False)
        except json.JSONDecodeError:
            args = "{}"
    else:
        args = "{}"
    safe_output = sanitize_for_provider(output)
    return [
        {"type": "function_call", "call_id": call_id, "name": name, "arguments": args},
        {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(safe_output, ensure_ascii=False, default=str),
        },
    ]


def conversation_input(
    db: Session, user_id: UUID, conversation_id: UUID
) -> list[dict[str, object]]:
    rows = db.scalars(
        select(AIMessage)
        .where(
            AIMessage.user_id == user_id,
            AIMessage.conversation_id == conversation_id,
            AIMessage.role.in_(("USER", "ASSISTANT", "TOOL")),
        )
        .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
        .limit(CONTEXT_MESSAGE_LIMIT)
    ).all()
    input_items: list[dict[str, object]] = []
    for row in reversed(rows):
        if row.role == "TOOL":
            input_items.extend(_tool_history_items(row))
        else:
            role = "user" if row.role == "USER" else "assistant"
            content = _safe_text_for_provider(row.content) if role == "user" else row.content
            input_items.append({"role": role, "content": content})
    return input_items


def _instructions(db: Session, user_id: UUID) -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    local_now = datetime.now(UTC).astimezone(FINANCIAL_ZONE)
    memories = db.scalars(
        select(AIMemory)
        .where(AIMemory.user_id == user_id)
        .order_by(AIMemory.created_at.desc())
        .limit(20)
    ).all()
    preference_lines = [f"- {_safe_text_for_provider(memory.content)}" for memory in memories]
    if not preference_lines:
        preference_lines = ["(nenhuma preferência salva)"]
    return (
        f"{prompt}\n\n"
        "## Dados da sessão\n"
        f"Data local atual: {current_financial_date().isoformat()}\n"
        f"Horário local: {local_now.strftime('%H:%M')}\n"
        "Preferências explícitas salvas pelo usuário:\n" + "\n".join(preference_lines)
    )


def _assistant_message(
    db: Session,
    conversation: AIConversation,
    user: User,
    content: str,
    cards: list[dict[str, object]],
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    cached_input_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    duration_ms: int | None = None,
    diagnostic_status: str = "SUCCEEDED",
    diagnostic_error: str | None = None,
) -> AIMessage:
    message = AIMessage(
        user_id=user.id,
        conversation_id=conversation.id,
        role="ASSISTANT",
        content=content,
        structured_content=cards or None,
        model=model,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=(
            None
            if settings.ai_provider == "chatgpt_plan"
            else estimated_cost(
                model, input_tokens, cached_input_tokens, cache_write_tokens, output_tokens
            )
        ),
        duration_ms=duration_ms,
        diagnostic_status=diagnostic_status,
        diagnostic_error=diagnostic_error,
        created_at=datetime.now(UTC),
    )
    db.add(message)
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    return message


def _tool_message(
    db: Session,
    conversation: AIConversation,
    user: User,
    call_id: str,
    name: str,
    arguments: object,
    result: ToolResult,
) -> AIMessage:
    structured = {
        "call_id": call_id,
        "name": name,
        "arguments": result.input_data if result.input_data else arguments,
        "output": result.output,
    }
    message = AIMessage(
        user_id=user.id,
        conversation_id=conversation.id,
        role="TOOL",
        content=json.dumps(result.output, ensure_ascii=False, default=str),
        structured_content=structured,
        created_at=datetime.now(UTC),
    )
    db.add(message)
    db.flush()
    return message


def _decode_arguments(raw: str) -> object:
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("A ferramenta enviou parâmetros em formato inválido.") from error
    if not isinstance(value, dict):
        raise ValueError("A ferramenta enviou parâmetros em formato inválido.")
    return value


def _function_call_item(call: FunctionCall, result: ToolResult) -> dict[str, object]:
    arguments: object = result.input_data
    if not arguments:
        try:
            arguments = json.loads(call.arguments)
        except json.JSONDecodeError:
            arguments = {}
    safe_arguments = sanitize_for_provider(arguments)
    return {
        "type": "function_call",
        "call_id": call.call_id,
        "name": call.name,
        "arguments": json.dumps(safe_arguments, ensure_ascii=False),
    }


def _record_tool_call(
    db: Session,
    user: User,
    conversation: AIConversation,
    message_id: UUID,
    call: FunctionCall,
    result: ToolResult,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_ms: int,
    cached_input_tokens: int | None = None,
    cache_write_tokens: int | None = None,
) -> AIToolCall:
    row = AIToolCall(
        user_id=user.id,
        conversation_id=conversation.id,
        message_id=message_id,
        provider_call_id=call.call_id[:100],
        tool_name=call.name[:100],
        input_sanitized=cast(dict[str, object], sanitize_for_provider(result.input_data)),
        output_sanitized=audit_summary(result),
        status=result.status,
        duration_ms=duration_ms,
        model=model,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=(
            None
            if settings.ai_provider == "chatgpt_plan"
            else estimated_cost(
                model, input_tokens, cached_input_tokens, cache_write_tokens, output_tokens
            )
        ),
        diagnostic_error=(
            "Falha na execução da ferramenta." if result.status == "FAILED" else None
        ),
        completed_at=datetime.now(UTC) if result.status != "PENDING_CONFIRMATION" else None,
    )
    db.add(row)
    db.flush()
    if result.status != "PENDING_CONFIRMATION":
        _tool_message(db, conversation, user, call.call_id, call.name, call.arguments, result)
    db.commit()
    db.refresh(row)
    return row


def _redacted_cards(cards: list[dict[str, object]]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], [sanitize_for_provider(card) for card in cards])


def _manual_expense_decision(
    db: Session,
    user: User,
    content: str,
    *,
    category_hint: str | None = None,
) -> ExpenseDecision | None:
    if not is_manual_expense_candidate(content):
        return None

    accounts = db.scalars(
        select(Account)
        .where(Account.user_id == user.id, Account.is_active.is_(True))
        .order_by(Account.name, Account.id)
    ).all()
    categories = db.scalars(
        select(Category)
        .where(
            Category.user_id == user.id,
            Category.type == "EXPENSE",
            Category.archived_at.is_(None),
        )
        .order_by(Category.name, Category.id)
    ).all()
    decision = parse_manual_expense(
        content,
        accounts,
        categories,
        current_financial_date(),
        category_hint=category_hint,
    )
    if decision.kind == "NOT_APPLICABLE":
        return None
    if decision.kind != "READY" or decision.arguments is None:
        return decision

    occurred_on = date.fromisoformat(decision.arguments["occurred_at"])
    account_id = UUID(decision.arguments["account_id"])
    category_id = UUID(decision.arguments["category_id"])
    category_name = db.scalar(
        select(Category.name).where(
            Category.user_id == user.id,
            Category.id == category_id,
        )
    )
    description = decision.arguments["description"]
    duplicate_descriptions = {_normalize_short_reply(description)}
    legacy_suffixes = {
        value.strip()
        for value in (category_hint, category_name)
        if isinstance(value, str) and value.strip()
    }
    duplicate_descriptions.update(
        _normalize_short_reply(f"{description} {suffix}") for suffix in legacy_suffixes
    )
    matching_transactions = db.execute(
        select(Transaction.id, Transaction.description).where(
            Transaction.user_id == user.id,
            Transaction.type == "EXPENSE",
            Transaction.account_id == account_id,
            Transaction.category_id == category_id,
            Transaction.amount == Decimal(decision.arguments["amount"]),
            Transaction.occurred_at >= financial_day_start(occurred_on),
            Transaction.occurred_at < financial_day_after(occurred_on),
        )
    ).all()
    duplicate_id = next(
        (
            transaction_id
            for transaction_id, existing_description in matching_transactions
            if _normalize_short_reply(existing_description) in duplicate_descriptions
        ),
        None,
    )
    if duplicate_id is not None:
        return ExpenseDecision(
            "CLARIFY",
            "Já existe um lançamento igual para esse dia. Para evitar duplicação, não criei outro. "
            "Se foi uma nova compra, me diga um detalhe do local ou da descrição.",
        )
    return decision


def _normalize_short_reply(content: str) -> str:
    decomposed = unicodedata.normalize("NFD", content.casefold())
    without_marks = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def _is_short_category_reply(content: str) -> bool:
    normalized = _normalize_short_reply(content)
    tokens = normalized.split()
    if (
        not normalized
        or len(normalized) > 80
        or len(tokens) > 4
        or not re.fullmatch(r"[\w]+(?:[\s&'-][\w]+)*", content.strip(), re.UNICODE)
    ):
        return False
    if re.search(r"\d", content):
        return False
    non_category_words = {
        "apenas",
        "como",
        "conexao",
        "criar",
        "crie",
        "deve",
        "gastei",
        "gasto",
        "gastos",
        "fatura",
        "limite",
        "mes",
        "quanto",
        "qnt",
        "responda",
        "saldo",
        "teste",
        "transferi",
    }
    return not set(tokens).intersection(non_category_words)


def _category_creation_request(content: str) -> str | None:
    prefix = re.match(
        r"^\s*(?:(?:sim|claro)\s*[, ]*)?(?:pode\s+)?"
        r"(?:crie|criar|cria|cadastre|cadastrar|adicione|adicionar)\b",
        content,
        re.IGNORECASE,
    )
    if prefix is None:
        return None

    target_match = re.search(
        r"\b(?:deve|deveria|vai)\s+entrar\s+como\s+"
        r"(?P<name>[\wÀ-ÿ][\wÀ-ÿ &'’-]{0,98}?)\s*[.!?]*\s*$",
        content,
        re.IGNORECASE,
    )
    if target_match is not None:
        name = target_match.group("name").strip()
    else:
        name_match = re.match(
            r"^\s*(?:(?:sim|claro)\s*[, ]*)?(?:pode\s+)?"
            r"(?:crie|criar|cria|cadastre|cadastrar|adicione|adicionar)\s+"
            r"(?P<name>[\wÀ-ÿ][\wÀ-ÿ &'’-]{0,98}?)\s*[.!?]*\s*$",
            content,
            re.IGNORECASE,
        )
        if name_match is None:
            return None
        name = name_match.group("name").strip()
        name = re.sub(
            r"^(?:(?:a|uma)\s+)?(?:nova\s+)?(?:categoria\s+)?"
            r"(?:(?:chamada|com o nome|com nome)\s+)?",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip()

    name = name.strip(" \t\r\n.,!?\"'“”‘’")
    if not name or len(name) > 100:
        return None
    return name


def _is_category_creation_confirmation(content: str) -> bool:
    normalized = _normalize_short_reply(content)
    return normalized in {
        "sim",
        "sim pode",
        "sim pode criar",
        "sim cria",
        "pode",
        "pode criar",
        "pode criar sim",
        "pode sim",
        "confirmo",
        "isso",
        "isso mesmo",
        "pode ser",
    }


def _is_category_creation_decline(content: str) -> bool:
    normalized = _normalize_short_reply(content)
    return normalized in {"nao", "nao cria", "nao precisa", "deixa", "deixa pra la"}


def _is_category_clarification(content: str) -> bool:
    normalized = _normalize_short_reply(content)
    return normalized.startswith(
        (
            "em qual categoria devo classificar esse gasto",
            "voce ainda nao cadastrou categorias de despesa",
            "nao encontrei uma categoria para este gasto",
            "nao encontrei essa categoria",
        )
    )


def _category_source_id(message: AIMessage) -> UUID | None:
    content = message.structured_content
    items = content if isinstance(content, list) else [content]
    for item in items:
        if not isinstance(item, dict) or item.get("type") != PENDING_EXPENSE_CLARIFICATION_TYPE:
            continue
        data = item.get("data")
        if not isinstance(data, dict) or data.get("field") != "category":
            continue
        source_id = data.get("source_message_id")
        if isinstance(source_id, str):
            try:
                return UUID(source_id)
            except ValueError:
                return None
    return None


def _category_suggestion(message: AIMessage) -> str | None:
    content = message.structured_content
    items = content if isinstance(content, list) else [content]
    for item in items:
        if not isinstance(item, dict) or item.get("type") != PENDING_EXPENSE_CLARIFICATION_TYPE:
            continue
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        suggested = data.get("suggested_category")
        if isinstance(suggested, str) and suggested.strip():
            return suggested
    return None


def _pending_category_suggestion(
    db: Session,
    user: User,
    conversation: AIConversation,
    source: AIMessage,
) -> str | None:
    latest_assistant = db.scalar(
        select(AIMessage)
        .where(
            AIMessage.user_id == user.id,
            AIMessage.conversation_id == conversation.id,
            AIMessage.role == "ASSISTANT",
        )
        .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
        .limit(1)
    )
    return (
        _category_suggestion(latest_assistant) if latest_assistant is not None else None
    ) or _suggested_expense_category(db, user, source.content)


def _suggested_expense_category(db: Session, user: User, content: str) -> str | None:
    suggested = suggest_expense_category_name(content)
    if suggested is None:
        return None
    categories = db.scalars(
        select(Category).where(
            Category.user_id == user.id,
            Category.type == "EXPENSE",
        )
    ).all()
    category_exists = any(
        _normalize_short_reply(category.name) == _normalize_short_reply(suggested)
        for category in categories
    )
    if category_exists:
        return None
    return suggested


def _pending_expense_category_source(
    db: Session,
    user: User,
    conversation: AIConversation,
    user_message: AIMessage,
) -> AIMessage | None:
    previous_messages = db.scalars(
        select(AIMessage)
        .where(
            AIMessage.user_id == user.id,
            AIMessage.conversation_id == conversation.id,
            AIMessage.id != user_message.id,
            AIMessage.role.in_(("USER", "ASSISTANT")),
        )
        .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
        .limit(8)
    ).all()

    for index, message in enumerate(previous_messages):
        if message.role != "ASSISTANT":
            continue

        source_id = _category_source_id(message)
        is_pending_category = source_id is not None or _is_category_clarification(message.content)
        if not is_pending_category:
            return None

        if source_id is not None:
            source = db.scalar(
                select(AIMessage).where(
                    AIMessage.id == source_id,
                    AIMessage.user_id == user.id,
                    AIMessage.conversation_id == conversation.id,
                    AIMessage.role == "USER",
                )
            )
            if source is not None and is_manual_expense_candidate(source.content):
                return source
            return None

        for older_message in previous_messages[index + 1 :]:
            if older_message.role == "ASSISTANT":
                break
            if older_message.role == "USER" and is_manual_expense_candidate(older_message.content):
                return older_message
        return None
    return None


def _category_clarification_marker(
    source_message_id: UUID, suggested_category: str | None = None
) -> list[dict[str, object]]:
    data: dict[str, object] = {
        "field": "category",
        "source_message_id": str(source_message_id),
    }
    if suggested_category is not None:
        data["suggested_category"] = suggested_category
    return [
        {
            "type": PENDING_EXPENSE_CLARIFICATION_TYPE,
            "data": data,
        }
    ]


def _unresolved_category_decision(
    decision: ExpenseDecision, suggested_category: str | None
) -> ExpenseDecision:
    options_prefix = "Suas categorias disponíveis incluem "
    options = decision.message.partition(options_prefix)[2].rstrip(". ") if decision.message else ""
    amount_detail = f" de R$ {format_brl(decision.amount)}" if decision.amount is not None else ""
    if suggested_category:
        message = (
            f"Não encontrei uma categoria para este gasto{amount_detail}. "
            f"Sugiro criar “{suggested_category}”. "
            "Posso criar a categoria e continuar o lançamento?"
        )
    elif options:
        message = (
            "Não encontrei uma categoria para este gasto. Suas categorias incluem "
            f"{options}. Escolha uma delas ou me diga o nome da categoria que devo criar; "
            "ainda não registrei o gasto."
        )
    else:
        message = (
            "Não encontrei uma categoria para este gasto. Diga o nome da categoria que devo criar; "
            "ainda não registrei o gasto."
        )
    return ExpenseDecision(
        "CLARIFY",
        message,
        clarification_field="category",
        amount=decision.amount,
    )


async def stream_assistant_reply(
    db: Session,
    user: User,
    conversation: AIConversation,
    user_message: AIMessage,
    provider: AIProvider,
) -> AsyncIterator[str]:
    turn_started = time.monotonic()
    category_creation_request = _category_creation_request(user_message.content)
    category_source = (
        _pending_expense_category_source(db, user, conversation, user_message)
        if _is_short_category_reply(user_message.content) or category_creation_request is not None
        else None
    )
    pending_suggestion = (
        _pending_category_suggestion(db, user, conversation, category_source)
        if category_source is not None
        else None
    )
    category_creation_name: str | None = None
    category_was_created = False
    category_declined = category_source is not None and _is_category_creation_decline(
        user_message.content
    )
    if category_source is None:
        expense_decision = _manual_expense_decision(db, user, user_message.content)
        clarification_source_id = user_message.id
    elif category_creation_request is not None:
        category_creation_name = category_creation_request
        expense_decision = _manual_expense_decision(
            db, user, category_source.content, category_hint=category_creation_name
        )
        clarification_source_id = category_source.id
    elif (
        _is_category_creation_confirmation(user_message.content) and pending_suggestion is not None
    ):
        category_creation_name = pending_suggestion
        expense_decision = _manual_expense_decision(
            db, user, category_source.content, category_hint=category_creation_name
        )
        clarification_source_id = category_source.id
    elif category_declined:
        expense_decision = _manual_expense_decision(db, user, category_source.content)
        clarification_source_id = category_source.id
    else:
        expense_decision = _manual_expense_decision(
            db, user, category_source.content, category_hint=user_message.content
        )
        clarification_source_id = category_source.id
        if (
            expense_decision is not None
            and expense_decision.kind == "CLARIFY"
            and expense_decision.clarification_field == "category"
            and _is_short_category_reply(user_message.content)
            and not _is_category_creation_confirmation(user_message.content)
        ):
            proposed_name = user_message.content.strip().strip(" \t\r\n.,!?\"'“”‘’")
            if proposed_name and len(proposed_name) <= 100:
                pending_suggestion = proposed_name[0].upper() + proposed_name[1:]

    if (
        expense_decision is not None
        and expense_decision.kind == "CLARIFY"
        and expense_decision.clarification_field == "category"
        and category_creation_name is None
        and not category_declined
    ):
        suggestion_source = category_source or user_message
        pending_suggestion = pending_suggestion or _suggested_expense_category(
            db, user, suggestion_source.content
        )
        expense_decision = _unresolved_category_decision(expense_decision, pending_suggestion)

    direct_expense = expense_decision is not None and expense_decision.kind == "READY"
    model = (
        LOCAL_EXPENSE_MODEL
        if expense_decision is not None or category_source is not None
        else choose_model(user_message.content)
    )
    instructions = _instructions(db, user.id) if expense_decision is None else ""
    cards: list[dict[str, object]] = []
    text_parts: list[str] = []
    input_items = conversation_input(db, user.id, conversation.id)
    tool_round = 0

    yield sse_event("start", {"message_id": str(user_message.id), "model": model})

    if category_declined and category_source is not None:
        content = (
            "Tudo bem, não criei a categoria nem registrei o gasto. "
            "Se quiser continuar, escolha uma categoria ou me peça para criar outra."
        )
        marker = _category_clarification_marker(category_source.id, pending_suggestion)
        _assistant_message(
            db,
            conversation,
            user,
            content,
            marker,
            model,
            None,
            None,
            duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
        )
        yield sse_event("text_delta", {"text": content})
        yield sse_event("done", {"status": "ok"})
        return

    if category_creation_name is not None and category_source is not None:
        existing_categories = db.scalars(
            select(Category).where(
                Category.user_id == user.id,
                Category.type == "EXPENSE",
            )
        ).all()
        matching_categories = [
            category
            for category in existing_categories
            if _normalize_short_reply(category.name)
            == _normalize_short_reply(category_creation_name)
        ]
        existing_category = next(
            (category for category in matching_categories if category.archived_at is None),
            None,
        )
        if existing_category is None and matching_categories:
            content = (
                f"A categoria “{category_creation_name}” já existe, mas está arquivada. "
                "Reative-a em Categorias para eu continuar; ainda não registrei o gasto."
            )
            marker = _category_clarification_marker(category_source.id, category_creation_name)
            _assistant_message(
                db,
                conversation,
                user,
                content,
                marker,
                model,
                None,
                None,
                duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
            )
            yield sse_event("text_delta", {"text": content})
            yield sse_event("done", {"status": "ok"})
            return

        if existing_category is None:
            category_call = FunctionCall(
                call_id=uuid4().hex,
                name="create_category",
                arguments=json.dumps(
                    {"name": category_creation_name, "category_type": "EXPENSE"},
                    ensure_ascii=False,
                ),
            )
            yield sse_event("tool_status", {"name": category_call.name, "status": "running"})
            category_result = execute_finance_tool(
                category_call.name,
                _decode_arguments(category_call.arguments),
                user,
                db,
            )
            audit = _record_tool_call(
                db,
                user,
                conversation,
                user_message.id,
                category_call,
                category_result,
                model,
                None,
                None,
                max(0, int((time.monotonic() - turn_started) * 1000)),
            )
            if category_result.status == "FAILED":
                content = (
                    "Não consegui criar essa categoria agora. "
                    "O gasto continua sem ser registrado; tente novamente."
                )
                category_failure_cards = category_result.cards or [
                    {"type": "error", "data": {"message": content}}
                ]
                _assistant_message(
                    db,
                    conversation,
                    user,
                    content,
                    category_failure_cards
                    + _category_clarification_marker(category_source.id, category_creation_name),
                    model,
                    None,
                    None,
                    duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
                    diagnostic_status="FAILED",
                    diagnostic_error="Falha ao criar categoria pelo assistente.",
                )
                yield sse_event("replace", {"text": content})
                yield sse_event("structured", {"items": category_failure_cards})
                yield sse_event("tool_status", {"name": category_call.name, "status": "failed"})
                yield sse_event("done", {"status": "error", "tool_call_id": str(audit.id)})
                return
            category_was_created = True
            yield sse_event("tool_status", {"name": category_call.name, "status": "succeeded"})

        expense_decision = _manual_expense_decision(
            db, user, category_source.content, category_hint=category_creation_name
        )
        if (
            expense_decision is not None
            and expense_decision.kind == "CLARIFY"
            and expense_decision.clarification_field == "category"
        ):
            expense_decision = _unresolved_category_decision(
                expense_decision, category_creation_name
            )
        direct_expense = expense_decision is not None and expense_decision.kind == "READY"

    if expense_decision is not None and expense_decision.kind == "CLARIFY":
        content = expense_decision.message or "Qual detalhe falta para registrar esse gasto?"
        if category_was_created and category_creation_name:
            content = f"Criei a categoria “{category_creation_name}”. {content}"
        clarification_cards = []
        if expense_decision.clarification_field == "category":
            clarification_cards = _category_clarification_marker(
                clarification_source_id, pending_suggestion
            )
        elif category_source is not None:
            # Keep the original expense available while asking for its remaining detail.
            clarification_cards = _category_clarification_marker(
                category_source.id, category_creation_name or pending_suggestion
            )
        _assistant_message(
            db,
            conversation,
            user,
            content,
            clarification_cards,
            model,
            None,
            None,
            duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
        )
        yield sse_event("text_delta", {"text": content})
        yield sse_event("done", {"status": "ok"})
        return

    while tool_round <= MAX_TOOL_ROUNDS:
        calls: list[FunctionCall] = []
        input_tokens: int | None = None
        cached_input_tokens: int | None = None
        cache_write_tokens: int | None = None
        output_tokens: int | None = None
        request_started = time.monotonic()
        response_output_items: list[dict[str, object]] = []
        try:
            if direct_expense and expense_decision is not None:
                calls.append(
                    FunctionCall(
                        call_id=uuid4().hex,
                        name="create_transaction",
                        arguments=json.dumps(expense_decision.arguments, ensure_ascii=False),
                    )
                )
            else:
                request = ProviderRequest(
                    model=model,
                    instructions=instructions,
                    input_items=input_items,
                    tools=tool_schemas(),
                    tool_choice="auto",
                )
                async for event in provider.stream(request):
                    if event.type == "text_delta" and event.text:
                        text_parts.append(event.text)
                        yield sse_event("text_delta", {"text": event.text})
                    elif event.type == "function_call" and event.function_call is not None:
                        calls.append(event.function_call)
                    elif event.type == "completed":
                        input_tokens = event.input_tokens
                        cached_input_tokens = event.cached_input_tokens
                        cache_write_tokens = event.cache_write_tokens
                        output_tokens = event.output_tokens
                        response_output_items = event.output_items
        except AIProviderError as error:
            content = str(error)
            provider_error_card: dict[str, object] = {
                "type": "error",
                "data": {"message": content},
            }
            _assistant_message(
                db,
                conversation,
                user,
                content,
                [provider_error_card],
                model,
                input_tokens,
                output_tokens,
                cached_input_tokens=cached_input_tokens,
                cache_write_tokens=cache_write_tokens,
                duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
                diagnostic_status="FAILED",
                diagnostic_error=f"Falha no provider de IA ({error.code}).",
            )
            yield sse_event("replace", {"text": content})
            yield sse_event("structured", {"items": [provider_error_card]})
            yield sse_event("done", {"status": "error"})
            return

        if not calls:
            content = "".join(text_parts).strip()
            if not content:
                content = (
                    "Não encontrei dados suficientes para responder. Pode me dar mais contexto?"
                )
                yield sse_event("replace", {"text": content})
            cards = _redacted_cards(cards)
            _assistant_message(
                db,
                conversation,
                user,
                content,
                cards,
                model,
                input_tokens,
                output_tokens,
                cached_input_tokens=cached_input_tokens,
                cache_write_tokens=cache_write_tokens,
                duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
            )
            if cards:
                yield sse_event("structured", {"items": cards})
            yield sse_event("done", {"status": "ok"})
            return

        # Text emitted before a function call is only a draft; clear it before the tool result.
        text_parts.clear()
        yield sse_event("reset", {})
        if tool_round == MAX_TOOL_ROUNDS:
            content = "Não consegui concluir a consulta em uma quantidade segura de etapas."
            max_round_error_card: dict[str, object] = {
                "type": "error",
                "data": {"message": content},
            }
            _assistant_message(
                db,
                conversation,
                user,
                content,
                [max_round_error_card],
                model,
                input_tokens,
                output_tokens,
                duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
                diagnostic_status="FAILED",
                diagnostic_error=content,
            )
            yield sse_event("replace", {"text": content})
            yield sse_event("structured", {"items": [max_round_error_card]})
            yield sse_event("done", {"status": "error"})
            return

        # With store=False, preserve encrypted reasoning items. Convert function calls
        # to the input shape instead of replaying response-only fields such as status/id.
        replayable_items = [
            item for item in response_output_items if item.get("type") == "reasoning"
        ]
        input_items.extend(replayable_items)
        for call in calls:
            yield sse_event("tool_status", {"name": call.name, "status": "running"})
            try:
                arguments = _decode_arguments(call.arguments)
                result = execute_finance_tool(call.name, arguments, user, db)
            except ValueError as error:
                result = ToolResult(
                    status="FAILED",
                    input_data={},
                    output={"ok": False, "error": str(error)},
                    cards=[{"type": "error", "data": {"message": str(error)}}],
                    error_message=str(error),
                )
            audit = _record_tool_call(
                db,
                user,
                conversation,
                user_message.id,
                call,
                result,
                model,
                input_tokens,
                output_tokens,
                max(0, int((time.monotonic() - request_started) * 1000)),
                cached_input_tokens,
                cache_write_tokens,
            )
            if result.status == "FAILED":
                detail = result.error_message or "verifique os dados e tente novamente."
                content = f"Não consegui concluir essa operação: {detail}"
                failure_cards: list[dict[str, object]] = result.cards or [
                    {"type": "error", "data": {"message": content}}
                ]
                _assistant_message(
                    db,
                    conversation,
                    user,
                    content,
                    failure_cards,
                    model,
                    None,
                    None,
                    duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
                    diagnostic_status="FAILED",
                    diagnostic_error="Falha na execução da ferramenta.",
                )
                yield sse_event("replace", {"text": content})
                yield sse_event("structured", {"items": failure_cards})
                yield sse_event("tool_status", {"name": call.name, "status": "failed"})
                yield sse_event("done", {"status": "error", "tool_call_id": str(audit.id)})
                return
            if result.status == "PENDING_CONFIRMATION":
                confirmation: dict[str, object] = (
                    dict(result.cards[0]) if result.cards else {"type": "confirmation", "data": {}}
                )
                confirmation["tool_call_id"] = str(audit.id)
                confirmation["status"] = "pending"
                content = (
                    "Esta alteração precisa da sua confirmação. "
                    "Revise os campos antes de continuar."
                )
                cards.append(confirmation)
                _assistant_message(
                    db,
                    conversation,
                    user,
                    content,
                    _redacted_cards(cards),
                    model,
                    None,
                    None,
                    duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
                    diagnostic_status="PENDING_CONFIRMATION",
                )
                yield sse_event("replace", {"text": content})
                yield sse_event("structured", {"items": _redacted_cards(cards)})
                yield sse_event("done", {"status": "confirmation_required"})
                return

            cards.extend(result.cards)
            if direct_expense and expense_decision is not None:
                formatted_amount = format_brl(expense_decision.amount or Decimal("0.00"))
                content = (
                    f"Pronto, registrei R$ {formatted_amount} "
                    f"em {expense_decision.description or 'despesa'}."
                )
                if category_was_created and category_creation_name:
                    content = (
                        f"Criei a categoria {category_creation_name} e "
                        f"{content[0].lower() + content[1:]}"
                    )
                safe_cards = _redacted_cards(cards)
                _assistant_message(
                    db,
                    conversation,
                    user,
                    content,
                    safe_cards,
                    model,
                    input_tokens,
                    output_tokens,
                    duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
                )
                yield sse_event("text_delta", {"text": content})
                if safe_cards:
                    yield sse_event("structured", {"items": safe_cards})
                yield sse_event("done", {"status": "ok"})
                return

            safe_output = sanitize_for_provider(result.output)
            input_items.append(_function_call_item(call, result))
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(safe_output, ensure_ascii=False, default=str),
                }
            )
            yield sse_event("tool_status", {"name": call.name, "status": "complete"})
        tool_round += 1

    content = "Não consegui concluir essa resposta. Tente novamente em uma nova mensagem."
    final_error_card: dict[str, object] = {"type": "error", "data": {"message": content}}
    _assistant_message(
        db,
        conversation,
        user,
        content,
        [final_error_card],
        model,
        None,
        None,
        duration_ms=max(0, int((time.monotonic() - turn_started) * 1000)),
        diagnostic_status="FAILED",
        diagnostic_error="O limite seguro de etapas da ferramenta foi atingido.",
    )
    yield sse_event("replace", {"text": content})
    yield sse_event("structured", {"items": [final_error_card]})
    yield sse_event("done", {"status": "error"})

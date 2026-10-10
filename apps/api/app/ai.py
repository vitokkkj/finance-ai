from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_chat import _assistant_message, _tool_message, stream_assistant_reply
from app.ai_provider import (
    AIProvider,
    OllamaProvider,
    OpenAIResponsesProvider,
    ollama_models_available,
)
from app.ai_schemas import (
    AIInteractionDiagnostic,
    AIMemoryResponse,
    AIMemoryWrite,
    AIMessageResponse,
    AIStatusResponse,
    AIUsageResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    ToolConfirmationResponse,
)
from app.ai_tools import audit_summary, execute_finance_tool
from app.auth import get_current_user
from app.chatgpt_plan import ChatGPTCredentialStore
from app.config import settings
from app.database import get_db
from app.finance_engine import financial_day_start
from app.models import AIConversation, AIMemory, AIMessage, AIToolCall, User

router = APIRouter(prefix="/api/ai", tags=["assistente"])
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
chatgpt_credentials = ChatGPTCredentialStore(settings.chatgpt_auth_dir)


async def get_ai_provider() -> AsyncIterator[AIProvider]:
    if settings.ai_provider == "ollama":
        provider: AIProvider = OllamaProvider(
            settings.ollama_base_url,
            settings.ollama_context_length,
            timeout_seconds=settings.ollama_timeout_seconds,
        )
    else:
        provider = OpenAIResponsesProvider(chatgpt_credentials)
    try:
        yield provider
    finally:
        await provider.close()


def _conversation_response(conversation: AIConversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _conversation_title_from_message(content: str) -> str:
    """Create a compact, readable label from the first message without another model call."""
    clean = " ".join(content.split()).strip(" .,!?:;\t\r\n")
    if not clean:
        return "Nova conversa"

    category = re.search(
        r"\bcategoria\s+(?P<name>[\wÀ-ÿ][\wÀ-ÿ&'’-]*(?:\s+(?!e\b|ou\b)[\wÀ-ÿ&'’-]+){0,2})",
        clean,
        re.IGNORECASE,
    )
    if category is not None:
        name = category.group("name").strip(" .,!?:;\t\r\n")
        if re.search(r"\b(gasto fixo|despesa fixa|recorrente|programad[oa])\b", clean, re.I):
            return f"Gasto fixo · {name}"[:60]
        if re.search(r"\b(crie|criar|cadastre|cadastrar|nova categoria)\b", clean, re.I):
            return f"Categoria · {name}"[:60]

    card = re.search(
        r"\b(?:cart[aã]o|fatura)\s+(?:do\s+)?(?P<name>Gold|Sicredi|Visa|Mastercard)\b",
        clean,
        re.I,
    )
    if re.search(r"\bfaturas?\b", clean, re.I) and card is not None:
        return f"Faturas · {card.group('name')}"[:60]

    item = re.search(
        r"\b(?:gastei|paguei|comprei)\b.{0,35}?"
        r"\b(?:com|em|no|na)\s+(?P<name>[\wÀ-ÿ][\wÀ-ÿ &'’-]{0,34})",
        clean,
        re.I,
    )
    if item is not None:
        name = item.group("name").strip(" .,!?:;\t\r\n")
        name = name[0].upper() + name[1:] if name else name
        return f"Gasto · {name}"[:60]

    clean = re.sub(
        r"^(?:(?:por favor|pode|quero|gostaria de|me ajude a|me ajuda a|"
        r"registre|registrar|crie|criar)\s+)+",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    if len(clean) <= 60:
        return clean[0].upper() + clean[1:]
    shortened = clean[:57].rsplit(" ", 1)[0].rstrip(" .,!?:;")
    return f"{shortened}…" if shortened else clean[:60]


def _get_conversation(db: Session, user: User, conversation_id: UUID) -> AIConversation:
    conversation = db.scalar(
        select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == user.id,
            AIConversation.archived_at.is_(None),
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return conversation


def _conversation_messages(
    db: Session, user: User, conversation: AIConversation
) -> list[AIMessageResponse]:
    rows = db.scalars(
        select(AIMessage)
        .where(
            AIMessage.user_id == user.id,
            AIMessage.conversation_id == conversation.id,
            AIMessage.role.in_(("USER", "ASSISTANT")),
        )
        .order_by(AIMessage.created_at, AIMessage.id)
    ).all()
    return [
        AIMessageResponse(
            id=row.id,
            role=cast(Literal["USER", "ASSISTANT"], row.role),
            content=row.content,
            structured_content=cast(list[dict[str, object]] | None, row.structured_content),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/status", response_model=AIStatusResponse)
async def ai_status(user: Annotated[User, Depends(get_current_user)]) -> AIStatusResponse:
    _ = user
    if settings.ai_provider == "ollama":
        models_available = await ollama_models_available(
            settings.ollama_base_url, {settings.ai_model_fast, settings.ai_model_smart}
        )
        configured = models_available
    else:
        configured = chatgpt_credentials.is_connected()
    return AIStatusResponse(
        configured=configured,
        provider=settings.ai_provider,
        fast_model=settings.ai_model_fast,
        smart_model=settings.ai_model_smart,
        diagnostics_enabled=settings.app_env.casefold() == "development",
    )


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ConversationResponse]:
    rows = db.scalars(
        select(AIConversation)
        .where(AIConversation.user_id == user.id, AIConversation.archived_at.is_(None))
        .order_by(AIConversation.updated_at.desc(), AIConversation.created_at.desc())
        .limit(100)
    ).all()
    return [_conversation_response(row) for row in rows]


@router.post(
    "/conversations",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    payload: ConversationCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConversationDetail:
    conversation = AIConversation(
        user_id=user.id,
        title=payload.title or "Nova conversa",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ConversationDetail(
        **_conversation_response(conversation).model_dump(),
        messages=[],
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConversationDetail:
    conversation = _get_conversation(db, user, conversation_id)
    return ConversationDetail(
        **_conversation_response(conversation).model_dump(),
        messages=_conversation_messages(db, user, conversation),
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
def rename_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConversationResponse:
    conversation = _get_conversation(db, user, conversation_id)
    conversation.title = payload.title
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conversation)
    return _conversation_response(conversation)


@router.post("/conversations/{conversation_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_conversation(
    conversation_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    conversation = _get_conversation(db, user, conversation_id)
    conversation.archived_at = datetime.now(UTC)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: UUID,
    payload: MessageCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
) -> StreamingResponse:
    conversation = _get_conversation(db, user, conversation_id)
    has_user_message = db.scalar(
        select(AIMessage.id)
        .where(
            AIMessage.user_id == user.id,
            AIMessage.conversation_id == conversation.id,
            AIMessage.role == "USER",
        )
        .limit(1)
    )
    message = AIMessage(
        user_id=user.id,
        conversation_id=conversation.id,
        role="USER",
        content=payload.content,
        created_at=datetime.now(UTC),
    )
    db.add(message)
    if has_user_message is None and conversation.title == "Nova conversa":
        conversation.title = _conversation_title_from_message(payload.content)
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)

    async def events() -> AsyncIterator[str]:
        async for item in stream_assistant_reply(db, user, conversation, message, provider):
            yield item

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/conversations/{conversation_id}/tool-calls/{tool_call_id}/confirm",
    response_model=ToolConfirmationResponse,
)
def confirm_tool_call(
    conversation_id: UUID,
    tool_call_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ToolConfirmationResponse:
    conversation = _get_conversation(db, user, conversation_id)
    call = db.scalar(
        select(AIToolCall).where(
            AIToolCall.id == tool_call_id,
            AIToolCall.user_id == user.id,
            AIToolCall.conversation_id == conversation.id,
        )
    )
    if call is None:
        raise HTTPException(status_code=404, detail="Confirmação não encontrada.")
    if call.status != "PENDING_CONFIRMATION":
        raise HTTPException(status_code=409, detail="Esta confirmação já foi processada.")
    result = execute_finance_tool(call.tool_name, call.input_sanitized, user, db, confirmed=True)
    call.status = result.status
    call.output_sanitized = audit_summary(result)
    call.completed_at = datetime.now(UTC)
    db.flush()
    if result.status == "SUCCEEDED":
        _tool_message(
            db,
            conversation,
            user,
            call.provider_call_id or str(call.id),
            call.tool_name,
            call.input_sanitized,
            result,
        )
        if call.tool_name == "set_card_invoice_opening_balances":
            text = "Faturas registradas."
        elif call.tool_name == "create_recurrence":
            text = (
                "Compromisso programado. "
                "O saldo só muda quando você marcar uma ocorrência como paga."
            )
        else:
            text = "Lançamento atualizado."
        cards = result.cards
    else:
        text = f"Não consegui concluir a alteração: {result.error_message or 'verifique os dados.'}"
        cards = result.cards or [{"type": "error", "data": {"message": text}}]
    _assistant_message(
        db, conversation, user, text, cards, call.model or settings.ai_model_fast, None, None
    )
    return ToolConfirmationResponse(
        id=call.id,
        status=cast(Literal["SUCCEEDED", "FAILED", "CANCELLED"], call.status),
        result={"text": text, "cards": cards},
    )


@router.post(
    "/conversations/{conversation_id}/tool-calls/{tool_call_id}/cancel",
    response_model=ToolConfirmationResponse,
)
def cancel_tool_call(
    conversation_id: UUID,
    tool_call_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ToolConfirmationResponse:
    conversation = _get_conversation(db, user, conversation_id)
    call = db.scalar(
        select(AIToolCall).where(
            AIToolCall.id == tool_call_id,
            AIToolCall.user_id == user.id,
            AIToolCall.conversation_id == conversation.id,
        )
    )
    if call is None:
        raise HTTPException(status_code=404, detail="Confirmação não encontrada.")
    if call.status != "PENDING_CONFIRMATION":
        raise HTTPException(status_code=409, detail="Esta confirmação já foi processada.")
    call.status = "CANCELLED"
    call.output_sanitized = {"status": "CANCELLED"}
    call.completed_at = datetime.now(UTC)
    text = "Alteração cancelada."
    card: dict[str, object] = {"type": "confirmation", "data": {"status": "cancelled"}}
    _assistant_message(
        db, conversation, user, text, [card], call.model or settings.ai_model_fast, None, None
    )
    return ToolConfirmationResponse(
        id=call.id,
        status="CANCELLED",
        result={"text": text, "cards": [card]},
    )


@router.get("/memories", response_model=list[AIMemoryResponse])
def list_memories(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AIMemoryResponse]:
    rows = db.scalars(
        select(AIMemory).where(AIMemory.user_id == user.id).order_by(AIMemory.created_at.desc())
    ).all()
    return [
        AIMemoryResponse(id=row.id, content=row.content, created_at=row.created_at) for row in rows
    ]


@router.post("/memories", response_model=AIMemoryResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: AIMemoryWrite,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AIMemoryResponse:
    memory = AIMemory(user_id=user.id, kind="PREFERENCE", content=payload.content)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return AIMemoryResponse(id=memory.id, content=memory.content, created_at=memory.created_at)


@router.patch("/memories/{memory_id}", response_model=AIMemoryResponse)
def update_memory(
    memory_id: UUID,
    payload: AIMemoryWrite,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AIMemoryResponse:
    memory = db.scalar(
        select(AIMemory).where(AIMemory.id == memory_id, AIMemory.user_id == user.id)
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Preferência não encontrada.")
    memory.content = payload.content
    db.commit()
    db.refresh(memory)
    return AIMemoryResponse(id=memory.id, content=memory.content, created_at=memory.created_at)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    memory = db.scalar(
        select(AIMemory).where(AIMemory.id == memory_id, AIMemory.user_id == user.id)
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Preferência não encontrada.")
    db.delete(memory)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/usage", response_model=AIUsageResponse)
def ai_usage(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AIUsageResponse:
    now = datetime.now(UTC).astimezone(SAO_PAULO)
    today_start = financial_day_start(now.date())
    tomorrow_start = financial_day_start(now.date() + timedelta(days=1))
    month_start = financial_day_start(now.date().replace(day=1))

    def aggregate(start: datetime, end: datetime | None) -> tuple[int, int, int, Decimal | None]:
        message_filter = [
            AIMessage.user_id == user.id,
            AIMessage.role == "ASSISTANT",
            AIMessage.model.is_not(None),
            AIMessage.created_at >= start,
        ]
        tool_filter = [
            AIToolCall.user_id == user.id,
            AIToolCall.model.is_not(None),
            AIToolCall.created_at >= start,
        ]
        if end is not None:
            message_filter.append(AIMessage.created_at < end)
            tool_filter.append(AIToolCall.created_at < end)
        messages = db.scalars(select(AIMessage).where(*message_filter)).all()
        tool_calls = db.scalars(select(AIToolCall).where(*tool_filter)).all()
        inputs = sum(row.input_tokens or 0 for row in messages) + sum(
            row.input_tokens or 0 for row in tool_calls
        )
        outputs = sum(row.output_tokens or 0 for row in messages) + sum(
            row.output_tokens or 0 for row in tool_calls
        )
        costs = [row.estimated_cost_usd for row in messages if row.estimated_cost_usd is not None]
        costs.extend(
            row.estimated_cost_usd for row in tool_calls if row.estimated_cost_usd is not None
        )
        cost = sum(costs, start=Decimal("0")) if costs else None
        return len(messages) + len(tool_calls), inputs, outputs, cost

    today = aggregate(today_start, tomorrow_start)
    month = aggregate(month_start, None)
    return AIUsageResponse(
        calls_today=today[0],
        input_tokens_today=today[1],
        output_tokens_today=today[2],
        cost_usd_today=today[3],
        calls_month=month[0],
        input_tokens_month=month[1],
        output_tokens_month=month[2],
        cost_usd_month=month[3],
    )


@router.get("/diagnostics", response_model=list[AIInteractionDiagnostic])
def ai_diagnostics(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AIInteractionDiagnostic]:
    if settings.app_env.casefold() != "development":
        raise HTTPException(status_code=404, detail="Diagnóstico não encontrado.")

    messages = db.scalars(
        select(AIMessage)
        .where(
            AIMessage.user_id == user.id,
            AIMessage.role == "ASSISTANT",
            AIMessage.model.is_not(None),
        )
        .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
        .limit(30)
    ).all()
    tool_calls = db.scalars(
        select(AIToolCall)
        .where(AIToolCall.user_id == user.id)
        .order_by(AIToolCall.created_at.desc(), AIToolCall.id.desc())
        .limit(30)
    ).all()

    diagnostics = [
        AIInteractionDiagnostic(
            id=row.id,
            created_at=row.created_at,
            conversation_id=row.conversation_id,
            model=row.model,
            tool_name=None,
            status=row.diagnostic_status or "SUCCEEDED",
            duration_ms=row.duration_ms,
            input_tokens=row.input_tokens,
            cached_input_tokens=row.cached_input_tokens,
            output_tokens=row.output_tokens,
            estimated_cost_usd=row.estimated_cost_usd,
            error_summary=row.diagnostic_error,
        )
        for row in messages
    ]
    diagnostics.extend(
        AIInteractionDiagnostic(
            id=row.id,
            created_at=row.created_at,
            conversation_id=row.conversation_id,
            model=row.model,
            tool_name=row.tool_name,
            status=row.status,
            duration_ms=row.duration_ms,
            input_tokens=row.input_tokens,
            cached_input_tokens=row.cached_input_tokens,
            output_tokens=row.output_tokens,
            estimated_cost_usd=row.estimated_cost_usd,
            error_summary=row.diagnostic_error,
        )
        for row in tool_calls
    )
    diagnostics.sort(key=lambda row: (row.created_at, str(row.id)), reverse=True)
    return diagnostics[:30]

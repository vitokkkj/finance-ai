from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import list_accounts
from app.cards import list_cards
from app.categories import create_category, list_categories
from app.finance_engine import current_financial_date
from app.finance_views import credit_card_response
from app.invoices import create_card_purchase, get_invoice
from app.models import Account, AIMemory, CardInvoice, CreditCard, Transaction, User
from app.schemas import (
    CardPurchaseCreate,
    CategoryCreate,
    TransactionCreate,
    TransactionUpdate,
    TransferCreate,
)
from app.transactions import (
    create_transaction,
    dashboard_summary,
    list_transactions,
    update_transaction,
)
from app.transfers import create_transfer


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetAccountsInput(ToolInput):
    include_archived: bool = False


class GetAccountBalanceInput(ToolInput):
    account_id: UUID


class GetTransactionsInput(ToolInput):
    start_date: date | None = None
    end_date: date | None = None
    account_id: UUID | None = None
    category_id: UUID | None = None
    movement_type: (
        Literal["INCOME", "EXPENSE", "TRANSFER", "CARD_PURCHASE", "CARD_PAYMENT"] | None
    ) = None
    limit: int = Field(default=30, ge=1, le=100)

    @model_validator(mode="after")
    def validate_period(self) -> GetTransactionsInput:
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("O período informado é inválido.")
        return self


class SearchTransactionsInput(ToolInput):
    query: str = Field(min_length=2, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(default=30, ge=1, le=100)


class CreateTransactionInput(ToolInput):
    account_id: UUID
    category_id: UUID
    movement_type: Literal["INCOME", "EXPENSE"]
    description: str = Field(min_length=1, max_length=200)
    amount: str
    occurred_at: date

    @field_validator("amount")
    @classmethod
    def validate_money(cls, value: str) -> str:
        return normalize_money(value)


class UpdateTransactionInput(ToolInput):
    transaction_id: UUID
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount: str | None = None
    occurred_at: date | None = None
    account_id: UUID | None = None
    category_id: UUID | None = None
    movement_type: Literal["INCOME", "EXPENSE"] | None = None

    @field_validator("amount")
    @classmethod
    def validate_money(cls, value: str | None) -> str | None:
        return normalize_money(value) if value is not None else None


class GetCategoriesInput(ToolInput):
    include_archived: bool = False


class CreateCategoryInput(ToolInput):
    name: str = Field(min_length=1, max_length=100)
    category_type: Literal["INCOME", "EXPENSE"]


class MonthInput(ToolInput):
    year: int | None = Field(default=None, ge=2000, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def validate_pair(self) -> MonthInput:
        if (self.year is None) != (self.month is None):
            raise ValueError("Informe ano e mês juntos ou deixe ambos vazios para este mês.")
        return self


class GetCreditCardsInput(ToolInput):
    include_archived: bool = False


class GetCardSummaryInput(ToolInput):
    credit_card_id: UUID


class GetInvoiceInput(ToolInput):
    invoice_id: UUID | None = None
    credit_card_id: UUID | None = None
    year: int | None = Field(default=None, ge=2000, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def validate_reference(self) -> GetInvoiceInput:
        if self.invoice_id is None and self.credit_card_id is None:
            raise ValueError("Informe uma fatura ou cartão para consultar.")
        if (self.year is None) != (self.month is None):
            raise ValueError("Informe ano e mês juntos.")
        return self


class GetInvoicePurchasesInput(ToolInput):
    invoice_id: UUID


class CreateCardPurchaseInput(ToolInput):
    credit_card_id: UUID
    category_id: UUID
    description: str = Field(min_length=1, max_length=200)
    amount: str
    occurred_at: date

    @field_validator("amount")
    @classmethod
    def validate_money(cls, value: str) -> str:
        return normalize_money(value)


class CreateTransferInput(ToolInput):
    source_account_id: UUID
    destination_account_id: UUID
    amount: str
    occurred_at: date

    @field_validator("amount")
    @classmethod
    def validate_money(cls, value: str) -> str:
        return normalize_money(value)


class SaveMemoryInput(ToolInput):
    content: str = Field(min_length=1, max_length=500)


class GetMemoriesInput(ToolInput):
    include_unused: bool = True


def normalize_money(value: str) -> str:
    """Convert a spoken/pt-BR money string to an exact two-place decimal string."""
    raw = value.strip().casefold()
    raw = re.sub(r"^r\$\s*", "", raw)
    spoken = re.fullmatch(r"(\d+)\s+reais?\s+e\s+(\d{1,2})", raw)
    if spoken is not None:
        raw = f"{spoken.group(1)}.{spoken.group(2).zfill(2)}"
    else:
        raw = re.sub(r"\s+reais?$", "", raw)
        raw = raw.replace(" ", "")
        if "," in raw:
            if raw.count(",") != 1:
                raise ValueError("Informe o valor em formato decimal válido.")
            whole, fraction = raw.split(",", 1)
            if not fraction.isdigit() or len(fraction) not in (1, 2):
                raise ValueError("Informe até duas casas decimais.")
            if "." in whole:
                if re.fullmatch(r"\d{1,3}(?:\.\d{3})*", whole) is None:
                    raise ValueError("Informe o valor em formato decimal válido.")
                whole = whole.replace(".", "")
            raw = f"{whole}.{fraction}"
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", raw) is None:
        raise ValueError("Informe o valor como texto decimal, sem sinal ou expoente.")
    try:
        amount = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError("Informe um valor monetário válido.") from error
    if not amount.is_finite() or amount <= Decimal("0"):
        raise ValueError("O valor precisa ser maior que zero.")
    return format(amount.quantize(Decimal("0.01")), ".2f")


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: Literal["SUCCEEDED", "FAILED", "PENDING_CONFIRMATION"]
    input_data: dict[str, object]
    output: dict[str, object]
    cards: list[dict[str, object]]
    error_message: str | None = None


ToolHandler = Callable[[Session, User, BaseModel], tuple[object, str | None]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[ToolInput]
    handler: ToolHandler
    requires_confirmation: bool = False
    confirmed_handler: ToolHandler | None = None


def _model_args(model: BaseModel) -> dict[str, object]:
    return cast(dict[str, object], model.model_dump(mode="json"))


def _serialize(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _call_args(schema: dict[str, object]) -> dict[str, object]:
    schema.pop("title", None)
    properties = cast(dict[str, object], schema.get("properties", {}))
    schema["required"] = list(properties)
    schema["additionalProperties"] = False
    return schema


def _account_lookup(db: Session, user: User, account_id: UUID) -> Account:
    account = db.scalar(select(Account).where(Account.id == account_id, Account.user_id == user.id))
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada.")
    return account


def _accounts(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(GetAccountsInput, args)
    rows = list_accounts(user, db, include_archived=payload.include_archived)
    return rows, "account_card"


def _account_balance(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(GetAccountBalanceInput, args)
    account = _account_lookup(db, user, payload.account_id)
    response = next(
        (row for row in list_accounts(user, db, include_archived=True) if row.id == account.id),
        None,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada.")
    return response, "account_card"


def _transactions(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(GetTransactionsInput, args)
    rows = list_transactions(
        user,
        db,
        start_date=payload.start_date,
        end_date=payload.end_date,
        account_id=payload.account_id,
        category_id=payload.category_id,
        type=payload.movement_type,
    )
    return rows[: payload.limit], "transaction_card"


def _search_transactions(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(SearchTransactionsInput, args)
    rows = list_transactions(
        user,
        db,
        start_date=payload.start_date,
        end_date=payload.end_date,
        q=payload.query,
    )
    return rows[: payload.limit], "transaction_card"


def _create_transaction(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(CreateTransactionInput, args)
    request = TransactionCreate(
        account_id=payload.account_id,
        category_id=payload.category_id,
        type=payload.movement_type,
        description=payload.description,
        amount=Decimal(payload.amount),
        occurred_at=payload.occurred_at,
    )
    return create_transaction(request, user, db), "transaction_card"


def _preview_transaction_update(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(UpdateTransactionInput, args)
    transaction = db.scalar(
        select(Transaction).where(
            Transaction.id == payload.transaction_id,
            Transaction.user_id == user.id,
        )
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado.")
    if transaction.type not in ("INCOME", "EXPENSE"):
        raise HTTPException(status_code=409, detail="Este tipo de movimento não pode ser alterado.")
    changes = {
        field: value
        for field, value in _model_args(payload).items()
        if field != "transaction_id" and value is not None
    }
    if not changes:
        raise HTTPException(status_code=422, detail="Informe ao menos uma alteração.")
    return {"transaction_id": str(transaction.id), "changes": changes}, "confirmation"


def _update_transaction(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(UpdateTransactionInput, args)
    values = _model_args(payload)
    transaction_id = UUID(str(values.pop("transaction_id")))
    changes: dict[str, object] = {}
    movement_type = values.pop("movement_type", None)
    if movement_type is not None:
        changes["type"] = movement_type
    changes.update({field: value for field, value in values.items() if value is not None})
    request = TransactionUpdate.model_validate(changes)
    return update_transaction(transaction_id, request, user, db), "transaction_card"


def _categories(db: Session, user: User, args: BaseModel) -> tuple[object, None]:
    payload = cast(GetCategoriesInput, args)
    return list_categories(user, db, include_archived=payload.include_archived), None


def _create_category(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(CreateCategoryInput, args)
    request = CategoryCreate(name=payload.name, type=payload.category_type)
    return create_category(request, user, db), "success"


def _period(args: MonthInput) -> tuple[int, int]:
    today = current_financial_date()
    return (args.year or today.year, args.month or today.month)


def _month_summary(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(MonthInput, args)
    year, month = _period(payload)
    summary = dashboard_summary(user, db, year, month)
    return {
        "period_start": summary.period_start,
        "period_end": summary.period_end,
        "income": summary.monthly_income,
        "expenses": summary.monthly_expenses,
        "result": summary.monthly_result,
    }, "financial_summary"


def _category_breakdown(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(MonthInput, args)
    year, month = _period(payload)
    summary = dashboard_summary(user, db, year, month)
    return {
        "period_start": summary.period_start,
        "period_end": summary.period_end,
        "categories": summary.expenses_by_category,
    }, "category_breakdown"


def _credit_cards(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(GetCreditCardsInput, args)
    return list_cards(user, db, include_archived=payload.include_archived), "card_summary"


def _card_summary(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(GetCardSummaryInput, args)
    card = db.scalar(
        select(CreditCard).where(
            CreditCard.id == payload.credit_card_id,
            CreditCard.user_id == user.id,
        )
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")
    return credit_card_response(db, card), "card_summary"


def _invoice(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(GetInvoiceInput, args)
    if payload.invoice_id is not None:
        invoice = db.scalar(
            select(CardInvoice).where(
                CardInvoice.id == payload.invoice_id,
                CardInvoice.user_id == user.id,
            )
        )
        if invoice is None:
            raise HTTPException(status_code=404, detail="Fatura não encontrada.")
        if payload.credit_card_id is not None and invoice.credit_card_id != payload.credit_card_id:
            raise HTTPException(status_code=404, detail="Fatura não encontrada para este cartão.")
    else:
        card = db.scalar(
            select(CreditCard).where(
                CreditCard.id == payload.credit_card_id,
                CreditCard.user_id == user.id,
            )
        )
        if card is None:
            raise HTTPException(status_code=404, detail="Cartão não encontrado.")
        invoices = db.scalars(
            select(CardInvoice)
            .where(
                CardInvoice.credit_card_id == card.id,
                CardInvoice.user_id == user.id,
            )
            .order_by(CardInvoice.closing_date.desc())
        ).all()
        if payload.year is not None and payload.month is not None:
            invoices = [
                row
                for row in invoices
                if row.closing_date.year == payload.year and row.closing_date.month == payload.month
            ]
        invoice = invoices[0] if invoices else None
        if invoice is None:
            return {"found": False, "credit_card_name": card.name}, "invoice_summary"
    return get_invoice(invoice.id, user, db), "invoice_summary"


def _invoice_purchases(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(GetInvoicePurchasesInput, args)
    response = get_invoice(payload.invoice_id, user, db)
    return response.purchases, "transaction_card"


def _create_card_purchase(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(CreateCardPurchaseInput, args)
    request = CardPurchaseCreate(
        credit_card_id=payload.credit_card_id,
        category_id=payload.category_id,
        description=payload.description,
        amount=Decimal(payload.amount),
        occurred_at=payload.occurred_at,
    )
    return create_card_purchase(request, user, db), "transaction_card"


def _create_transfer(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(CreateTransferInput, args)
    request = TransferCreate(
        source_account_id=payload.source_account_id,
        destination_account_id=payload.destination_account_id,
        amount=Decimal(payload.amount),
        occurred_at=payload.occurred_at,
    )
    return create_transfer(request, user, db), "transaction_card"


def _dashboard(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(MonthInput, args)
    year, month = _period(payload)
    return dashboard_summary(user, db, year, month), "financial_summary"


def _save_memory(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(SaveMemoryInput, args)
    content = payload.content.strip()
    memory = AIMemory(user_id=user.id, kind="PREFERENCE", content=content)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return {"id": memory.id, "content": memory.content}, "success"


def _get_memories(db: Session, user: User, args: BaseModel) -> tuple[object, None]:
    _ = cast(GetMemoriesInput, args)
    rows = db.scalars(
        select(AIMemory).where(AIMemory.user_id == user.id).order_by(AIMemory.created_at)
    ).all()
    return [{"id": row.id, "content": row.content} for row in rows], None


TOOL_DEFINITIONS = (
    ToolDefinition(
        "get_accounts",
        "Lista contas do usuário e seus saldos calculados.",
        GetAccountsInput,
        _accounts,
    ),
    ToolDefinition(
        "get_account_balance",
        "Consulta o saldo de uma conta própria.",
        GetAccountBalanceInput,
        _account_balance,
    ),
    ToolDefinition(
        "get_transactions",
        "Lista movimentos no período e filtros informados.",
        GetTransactionsInput,
        _transactions,
    ),
    ToolDefinition(
        "search_transactions",
        "Busca lançamentos por descrição, categoria ou cartão.",
        SearchTransactionsInput,
        _search_transactions,
    ),
    ToolDefinition(
        "create_transaction",
        "Registra receita ou despesa comum já ocorrida.",
        CreateTransactionInput,
        _create_transaction,
    ),
    ToolDefinition(
        "update_transaction",
        "Prepara uma alteração de lançamento, sempre pedindo confirmação antes de aplicar.",
        UpdateTransactionInput,
        _preview_transaction_update,
        requires_confirmation=True,
        confirmed_handler=_update_transaction,
    ),
    ToolDefinition(
        "get_categories",
        "Lista categorias disponíveis do usuário.",
        GetCategoriesInput,
        _categories,
    ),
    ToolDefinition(
        "create_category",
        "Só cria uma categoria após pedido explícito ou confirmação de sugestão.",
        CreateCategoryInput,
        _create_category,
    ),
    ToolDefinition(
        "get_month_summary",
        "Consulta resumo mensal calculado pelo Finance Engine.",
        MonthInput,
        _month_summary,
    ),
    ToolDefinition(
        "get_category_breakdown",
        "Consulta despesas agrupadas por categoria pelo Finance Engine.",
        MonthInput,
        _category_breakdown,
    ),
    ToolDefinition(
        "get_credit_cards",
        "Lista cartões e seus limites calculados.",
        GetCreditCardsInput,
        _credit_cards,
    ),
    ToolDefinition(
        "get_card_summary",
        "Consulta limites e próximo vencimento de um cartão.",
        GetCardSummaryInput,
        _card_summary,
    ),
    ToolDefinition(
        "get_invoice",
        "Consulta uma fatura por ID ou a fatura mais recente de um cartão.",
        GetInvoiceInput,
        _invoice,
    ),
    ToolDefinition(
        "get_invoice_purchases",
        "Lista compras associadas à fatura informada.",
        GetInvoicePurchasesInput,
        _invoice_purchases,
    ),
    ToolDefinition(
        "create_card_purchase",
        "Registra uma compra já feita em cartão de crédito.",
        CreateCardPurchaseInput,
        _create_card_purchase,
    ),
    ToolDefinition(
        "create_transfer",
        "Registra uma transferência própria já realizada entre contas.",
        CreateTransferInput,
        _create_transfer,
    ),
    ToolDefinition(
        "get_dashboard_summary",
        "Consulta o painel financeiro calculado pelo Finance Engine.",
        MonthInput,
        _dashboard,
    ),
    ToolDefinition(
        "save_explicit_memory",
        "Guarda uma preferência somente quando o usuário pedir para lembrar.",
        SaveMemoryInput,
        _save_memory,
    ),
    ToolDefinition(
        "get_explicit_memories",
        "Lista preferências que o usuário pediu para lembrar.",
        GetMemoriesInput,
        _get_memories,
    ),
)


def tool_schemas() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "name": definition.name,
            "description": definition.description,
            "parameters": _call_args(definition.input_model.model_json_schema()),
            "strict": True,
        }
        for definition in TOOL_DEFINITIONS
    ]


def tool_names() -> set[str]:
    return {definition.name for definition in TOOL_DEFINITIONS}


def _sanitize_string(value: str) -> str:
    value = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b", "[CPF ocultado]", value)
    value = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "[e-mail ocultado]", value)
    return re.sub(r"(?<!\w)\d{8,}(?!\w)", "[número longo ocultado]", value)


def sanitize_for_provider(value: object, key: str = "") -> object:
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_for_provider(item, str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_for_provider(item, key) for item in value]
    if isinstance(value, str) and not (key == "id" or key.endswith("_id")):
        return _sanitize_string(value)
    return value


def execute_finance_tool(
    name: str,
    arguments: object,
    user: User,
    db: Session,
    *,
    confirmed: bool = False,
) -> ToolResult:
    definition = next((item for item in TOOL_DEFINITIONS if item.name == name), None)
    if definition is None:
        return ToolResult(
            status="FAILED",
            input_data={},
            output={"ok": False, "error": "Ferramenta desconhecida."},
            cards=[{"type": "error", "data": {"message": "A ferramenta solicitada não existe."}}],
            error_message="A ferramenta solicitada não existe.",
        )
    try:
        if not isinstance(arguments, dict):
            raise ValueError("Os argumentos da ferramenta precisam ser um objeto.")
        payload = definition.input_model.model_validate(arguments)
        input_data = _model_args(payload)
        if definition.requires_confirmation and not confirmed:
            preview, card_type = definition.handler(db, user, payload)
            card = {"type": card_type or "confirmation", "data": _serialize(preview)}
            return ToolResult(
                status="PENDING_CONFIRMATION",
                input_data=input_data,
                output={"ok": True, "status": "pending_confirmation", "data": _serialize(preview)},
                cards=[card],
            )
        handler = definition.confirmed_handler if confirmed else None
        result, card_type = (handler or definition.handler)(db, user, payload)
        serialized = _serialize(result)
        cards: list[dict[str, object]] = []
        if card_type is not None:
            cards.append({"type": card_type, "data": serialized})
        return ToolResult(
            status="SUCCEEDED",
            input_data=input_data,
            output={"ok": True, "data": serialized},
            cards=cards,
        )
    except ValidationError:
        db.rollback()
        message = "Os dados da ferramenta não passaram pela validação."
    except HTTPException as error:
        db.rollback()
        message = str(error.detail)
    except (ValueError, InvalidOperation) as error:
        db.rollback()
        message = str(error)
    except Exception:
        db.rollback()
        message = "A ferramenta não conseguiu concluir a operação."
    return ToolResult(
        status="FAILED",
        input_data={},
        output={"ok": False, "error": _sanitize_string(message)},
        cards=[{"type": "error", "data": {"message": _sanitize_string(message)}}],
        error_message=_sanitize_string(message),
    )


def audit_summary(result: ToolResult) -> dict[str, object]:
    if result.status == "SUCCEEDED":
        data = result.output.get("data")
        if isinstance(data, list):
            count = len(data)
            kind = "lista"
        elif isinstance(data, dict):
            count = 1
            kind = "registro"
        else:
            count = 0
            kind = "resultado"
        return {"status": result.status, "kind": kind, "items": count}
    if result.status == "PENDING_CONFIRMATION":
        return {"status": result.status}
    return {"status": result.status, "error": _sanitize_string(result.error_message or "Falha")}

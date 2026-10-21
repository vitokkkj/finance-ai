from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
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
from app.cards import create_card, list_cards
from app.categories import create_category, list_categories
from app.finance_engine import billing_cycle_for_due_month, current_financial_date
from app.finance_views import credit_card_response
from app.invoices import (
    create_card_purchase,
    get_invoice,
    invoice_opening_balance_from_total,
    set_invoice_opening_balances,
)
from app.models import Account, AIMemory, CardInvoice, Category, CreditCard, Transaction, User
from app.recurrences import create_recurrence_for_user, validate_recurrence
from app.schemas import (
    CardInvoiceOpeningBalanceSet,
    CardPurchaseCreate,
    CategoryCreate,
    CreditCardCreate,
    RecurrenceCreate,
    TransactionCreate,
    TransactionUpdate,
    TransferCreate,
)
from app.transactions import (
    _calculate_dashboard_summary,
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


class CreateCreditCardInput(ToolInput):
    name: str = Field(min_length=1, max_length=100)
    institution: str | None = Field(default=None, max_length=100)
    credit_limit: str = Field(min_length=1, max_length=32)
    closing_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome do cartão.")
        return normalized

    @field_validator("institution")
    @classmethod
    def normalize_institution(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("credit_limit")
    @classmethod
    def validate_credit_limit(cls, value: str) -> str:
        raw = value.strip()
        if re.fullmatch(r"\d+(?:\.\d{1,2})?", raw) is None:
            raise ValueError("Informe o limite como texto decimal exato.")
        try:
            amount = Decimal(raw)
        except InvalidOperation as error:
            raise ValueError("Informe um limite válido.") from error
        if not amount.is_finite() or amount < Decimal("0"):
            raise ValueError("O limite do cartão não pode ser negativo.")
        return format(amount.quantize(Decimal("0.01")), ".2f")


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


class InvoiceOpeningBalanceInput(ToolInput):
    due_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount: str = Field(min_length=1, max_length=32)

    @field_validator("amount")
    @classmethod
    def validate_money(cls, value: str) -> str:
        normalized = normalize_money(value)
        CardInvoiceOpeningBalanceSet(due_month="2000-01", amount=normalized)
        return normalized


class SetInvoiceOpeningBalancesInput(ToolInput):
    credit_card_id: UUID
    invoices: list[InvoiceOpeningBalanceInput] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def validate_unique_cycles(self) -> SetInvoiceOpeningBalancesInput:
        months = [item.due_month for item in self.invoices]
        if len(months) != len(set(months)):
            raise ValueError("Cada mês de vencimento deve aparecer uma única vez.")
        return self


class CreateCreditCardWithInvoicesInput(CreateCreditCardInput):
    invoices: list[InvoiceOpeningBalanceInput] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def validate_unique_cycles(self) -> CreateCreditCardWithInvoicesInput:
        months = [item.due_month for item in self.invoices]
        if len(months) != len(set(months)):
            raise ValueError("Cada mês de vencimento deve aparecer uma única vez.")
        return self


class CreateTransferInput(ToolInput):
    source_account_id: UUID
    destination_account_id: UUID
    amount: str
    occurred_at: date

    @field_validator("amount")
    @classmethod
    def validate_money(cls, value: str) -> str:
        return normalize_money(value)


class CreateRecurrenceInput(ToolInput):
    account_id: UUID
    category_id: UUID
    movement_type: Literal["INCOME", "EXPENSE"]
    description: str = Field(min_length=1, max_length=200)
    amount: str
    frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "YEARLY"]
    interval: int = Field(ge=1, le=365)
    starts_on: date
    ends_on: date | None
    notes: str | None

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


def financial_tool_call_fingerprint(name: str, arguments: object) -> str | None:
    """Return a stable signature for a validated financial creation tool call."""
    if name not in {"create_transaction", "create_transfer", "create_card_purchase"}:
        return None
    if not isinstance(arguments, dict):
        return None
    definition = next((item for item in TOOL_DEFINITIONS if item.name == name), None)
    if definition is None:
        return None
    try:
        payload = definition.input_model.model_validate(arguments)
    except ValidationError:
        return None
    canonical = json.dumps(
        {"tool": name, "arguments": _model_args(payload)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
        limit=payload.limit,
    )
    return rows.items, "transaction_card"


def _search_transactions(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(SearchTransactionsInput, args)
    rows = list_transactions(
        user,
        db,
        start_date=payload.start_date,
        end_date=payload.end_date,
        q=payload.query,
        limit=payload.limit,
    )
    return rows.items, "transaction_card"


def _create_transaction(
    db: Session, user: User, args: BaseModel, *, idempotency_key: str | None = None
) -> tuple[object, str]:
    payload = cast(CreateTransactionInput, args)
    request = TransactionCreate(
        account_id=payload.account_id,
        category_id=payload.category_id,
        type=payload.movement_type,
        description=payload.description,
        amount=Decimal(payload.amount),
        occurred_at=payload.occurred_at,
    )
    transaction = create_transaction(request, user, db, idempotency_key=idempotency_key)
    return transaction, "transaction_card"


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
    if payload.category_id is not None:
        category = db.scalar(
            select(Category).where(
                Category.id == payload.category_id,
                Category.user_id == user.id,
            )
        )
        if category is None:
            raise HTTPException(status_code=404, detail="Categoria não encontrada.")
        if category.archived_at is not None:
            raise HTTPException(status_code=409, detail="A categoria está arquivada.")
        if category.type != transaction.type:
            raise HTTPException(
                status_code=422,
                detail="O tipo da categoria precisa corresponder ao tipo do lançamento.",
            )
        changes["category_id"] = category.name
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


def _month_forecast(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(MonthInput, args)
    year, month = _period(payload)
    period_start = date(year, month, 1)
    period_end = date(year, month, monthrange(year, month)[1])
    summary = _calculate_dashboard_summary(
        user,
        db,
        year,
        month,
        forecast_period=(period_start, period_end),
    )
    expenses = sum(
        (item.amount for item in summary.forecast_items if item.type == "EXPENSE"),
        start=Decimal("0.00"),
    )
    income = sum(
        (item.amount for item in summary.forecast_items if item.type == "INCOME"),
        start=Decimal("0.00"),
    )
    return {
        "period_start": period_start,
        "period_end": period_end,
        "expenses": expenses,
        "income": income,
        "items": summary.forecast_items,
        "unassigned_invoice_total": summary.forecast_unassigned_invoice_total,
    }, "monthly_forecast"


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


def _credit_card_preview(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(CreateCreditCardInput, args)
    existing_cards = db.scalars(
        select(CreditCard).where(
            CreditCard.user_id == user.id,
            CreditCard.is_active.is_(True),
        )
    ).all()
    institution_key = (payload.institution or "").casefold()
    duplicate = next(
        (
            card
            for card in existing_cards
            if card.name.casefold() == payload.name.casefold()
            and (card.institution or "").casefold() == institution_key
        ),
        None,
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Este cartão já está cadastrado.")
    return {
        "title": "Confirme o cadastro do cartão",
        "changes": {
            "Cartão": payload.name,
            "Instituição": payload.institution or "Não informada",
            "Limite": format_brl(Decimal(payload.credit_limit)),
            "Fecha dia": str(payload.closing_day),
            "Vence dia": str(payload.due_day),
        },
        "message": "O cartão só será cadastrado depois da sua confirmação.",
    }, "confirmation"


def _create_credit_card(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(CreateCreditCardInput, args)
    request = CreditCardCreate(
        name=payload.name,
        institution=payload.institution,
        credit_limit=payload.credit_limit,
        closing_day=payload.closing_day,
        due_day=payload.due_day,
    )
    return create_card(request, user, db), "card_summary"


def _create_credit_card_with_invoices_preview(
    db: Session, user: User, args: BaseModel
) -> tuple[object, str]:
    payload = cast(CreateCreditCardWithInvoicesInput, args)
    card_preview, _ = _credit_card_preview(db, user, payload)
    preview = cast(dict[str, object], card_preview)
    changes = cast(dict[str, str], preview["changes"])
    month_names = (
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    )
    for item in sorted(payload.invoices, key=lambda value: value.due_month):
        year, month = (int(part) for part in item.due_month.split("-"))
        cycle = billing_cycle_for_due_month(year, month, payload.closing_day, payload.due_day)
        label = (
            f"Vencimento {month_names[month - 1].capitalize()}/{year} · "
            f"ciclo {cycle.period_start:%d/%m}–{cycle.period_end:%d/%m/%Y}"
        )
        changes[label] = format_brl(Decimal(item.amount))
    return {
        "title": "Confirme o cartão e as faturas",
        "changes": changes,
        "message": (
            "O cartão e os totais das faturas serão registrados juntos. "
            "Nenhuma compra individual ou despesa histórica será criada."
        ),
    }, "confirmation"


def _create_credit_card_with_invoices(
    db: Session, user: User, args: BaseModel
) -> tuple[object, str]:
    payload = cast(CreateCreditCardWithInvoicesInput, args)
    _credit_card_preview(db, user, payload)
    card = CreditCard(
        user_id=user.id,
        name=payload.name,
        institution=payload.institution,
        credit_limit=Decimal(payload.credit_limit),
        currency="BRL",
        closing_day=payload.closing_day,
        due_day=payload.due_day,
    )
    db.add(card)
    db.flush()
    invoices = [
        CardInvoiceOpeningBalanceSet(
            due_month=item.due_month,
            amount=item.amount,
        )
        for item in payload.invoices
    ]
    set_invoice_opening_balances(
        db,
        user,
        card.id,
        invoices,
        amounts_are_invoice_totals=True,
    )
    db.commit()
    db.refresh(card)
    return credit_card_response(db, card), "card_summary"


def _create_card_purchase(
    db: Session,
    user: User,
    args: BaseModel,
    *,
    idempotency_key: str | None = None,
) -> tuple[object, str]:
    payload = cast(CreateCardPurchaseInput, args)
    request = CardPurchaseCreate(
        credit_card_id=payload.credit_card_id,
        category_id=payload.category_id,
        description=payload.description,
        amount=Decimal(payload.amount),
        occurred_at=payload.occurred_at,
    )
    return (
        create_card_purchase(request, user, db, idempotency_key=idempotency_key),
        "transaction_card",
    )


def _card_invoice_opening_balance_preview(
    db: Session, user: User, args: BaseModel
) -> tuple[object, str]:
    payload = cast(SetInvoiceOpeningBalancesInput, args)
    card = db.scalar(
        select(CreditCard).where(
            CreditCard.id == payload.credit_card_id,
            CreditCard.user_id == user.id,
            CreditCard.is_active.is_(True),
        )
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão ativo não encontrado.")

    changes: dict[str, str] = {
        "Cartão": " · ".join(part for part in (card.name, card.institution) if part)
    }
    month_names = (
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    )
    for item in sorted(payload.invoices, key=lambda value: value.due_month):
        year, month = (int(part) for part in item.due_month.split("-"))
        cycle = billing_cycle_for_due_month(year, month, card.closing_day, card.due_day)
        invoice = db.scalar(
            select(CardInvoice).where(
                CardInvoice.credit_card_id == card.id,
                CardInvoice.user_id == user.id,
                CardInvoice.closing_date == cycle.closing_date,
            )
        )
        amount = Decimal(item.amount)
        current_opening = Decimal("0.00")
        purchase_total = Decimal("0.00")
        paid_amount = Decimal("0.00")
        opening_balance = amount
        if invoice is not None:
            purchase_total, opening_balance, paid_amount = invoice_opening_balance_from_total(
                db, invoice, amount
            )
            current_opening = invoice.opening_balance

        label = f"Vencimento {month_names[month - 1].capitalize()}/{year}"
        summary = (
            f"fatura informada {format_brl(amount)} · "
            f"compras já lançadas {format_brl(purchase_total)} · "
            f"dívida inicial a registrar {format_brl(opening_balance)} · "
            f"total previsto {format_brl(amount)}"
        )
        if paid_amount > 0:
            summary += f" · {format_brl(paid_amount)} já pago"
        if current_opening > 0:
            summary += f" · saldo inicial atual: {format_brl(current_opening)}"
        changes[label] = summary

    return {
        "changes": changes,
        "message": (
            "O valor informado é o total atual da fatura. Compras já lançadas são descontadas "
            "desse total para evitar duplicidade; o restante entra como dívida existente, sem "
            "criar compras nem despesas históricas."
        ),
    }, "confirmation"


def _set_card_invoice_opening_balances(
    db: Session, user: User, args: BaseModel
) -> tuple[object, str]:
    payload = cast(SetInvoiceOpeningBalancesInput, args)
    requests = [
        CardInvoiceOpeningBalanceSet(
            due_month=item.due_month,
            amount=item.amount,
        )
        for item in payload.invoices
    ]
    card, invoices = set_invoice_opening_balances(
        db,
        user,
        payload.credit_card_id,
        requests,
        amounts_are_invoice_totals=True,
    )
    db.commit()
    months = ", ".join(
        f"{int(item.due_month[5:]):02d}/{item.due_month[:4]}"
        for item in payload.invoices
    )
    return {
        "message": (
            f"Registrei os saldos iniciais das faturas com vencimento em {months} "
            f"no cartão {card.name}. "
            "Eles representam dívidas existentes e não criaram compras ou despesas históricas."
        ),
        "invoice_count": len(invoices),
    }, "success"


def _recurrence_request(payload: CreateRecurrenceInput) -> RecurrenceCreate:
    return RecurrenceCreate(
        account_id=payload.account_id,
        category_id=payload.category_id,
        type=payload.movement_type,
        description=payload.description,
        amount=Decimal(payload.amount),
        frequency=payload.frequency,
        interval=payload.interval,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        notes=payload.notes,
    )


def _recurrence_preview(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(CreateRecurrenceInput, args)
    request = _recurrence_request(payload)
    account, category = validate_recurrence(request, user, db)
    frequency_labels = {
        "DAILY": ("dia", "dias"),
        "WEEKLY": ("semana", "semanas"),
        "MONTHLY": ("mês", "meses"),
        "YEARLY": ("ano", "anos"),
    }
    cadence = (
        f"A cada {request.interval} {frequency_labels[request.frequency][1]}"
        if request.interval > 1
        else {
            "DAILY": "Diária",
            "WEEKLY": "Semanal",
            "MONTHLY": "Mensal",
            "YEARLY": "Anual",
        }[request.frequency]
    )
    changes: dict[str, str] = {
        "Descrição": request.description,
        "Tipo": "Despesa" if request.type == "EXPENSE" else "Receita",
        "Valor": format_brl(request.amount),
        "Conta": account.name,
        "Categoria": category.name,
        "Frequência": cadence,
        "Primeira ocorrência": request.starts_on.strftime("%d/%m/%Y"),
        "Última ocorrência": (
            request.ends_on.strftime("%d/%m/%Y")
            if request.ends_on is not None
            else "Sem data final"
        ),
        "Observação": request.notes or "—",
    }
    return {
        "title": "Confirmar compromisso",
        "changes": changes,
        "message": (
            "Este compromisso ficará em Programados. O saldo não muda. "
            "Nenhuma despesa é registrada até que você marque uma ocorrência como paga."
        ),
    }, "confirmation"


def _create_recurrence(db: Session, user: User, args: BaseModel) -> tuple[object, str]:
    payload = cast(CreateRecurrenceInput, args)
    rule = create_recurrence_for_user(_recurrence_request(payload), user, db)
    end_description = (
        f" até {rule.ends_on.strftime('%d/%m/%Y')}" if rule.ends_on is not None else ""
    )
    return {
        "title": "Programado",
        "message": (
            f"Agendei “{rule.description}” por {format_brl(rule.amount)}, com primeira ocorrência "
            f"em {rule.starts_on.strftime('%d/%m/%Y')}{end_description}. "
            "O saldo só muda quando você marcar uma ocorrência como paga."
        ),
    }, "success"


def format_brl(amount: Decimal) -> str:
    whole, fraction = f"{amount:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"R$ {grouped},{fraction}"


def _create_transfer(
    db: Session, user: User, args: BaseModel, *, idempotency_key: str | None = None
) -> tuple[object, str]:
    payload = cast(CreateTransferInput, args)
    request = TransferCreate(
        source_account_id=payload.source_account_id,
        destination_account_id=payload.destination_account_id,
        amount=Decimal(payload.amount),
        occurred_at=payload.occurred_at,
    )
    return create_transfer(request, user, db, idempotency_key=idempotency_key), "transaction_card"


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
        "Consulta somente receitas e despesas já realizadas no mês informado.",
        MonthInput,
        _month_summary,
    ),
    ToolDefinition(
        "get_month_forecast",
        (
            "Consulta a previsão de compromissos do mês informado: recorrências não pagas, "
            "compromissos avulsos e faturas de cartão em aberto com vencimento nesse mês. "
            "Use para perguntas sobre gastos ou contas previstos de um mês específico; os valores "
            "são previstos, não realizados."
        ),
        MonthInput,
        _month_forecast,
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
        "create_credit_card",
        (
            "Prepara o cadastro de um cartão somente com nome, instituição, limite, dia de "
            "fechamento e vencimento fornecidos pelo usuário. Nunca invente esses dados. "
            "Sempre exige confirmação antes de criar o cartão."
        ),
        CreateCreditCardInput,
        _credit_card_preview,
        requires_confirmation=True,
        confirmed_handler=_create_credit_card,
    ),
    ToolDefinition(
        "create_credit_card_with_invoices",
        (
            "Prepara em uma única confirmação o cadastro de um cartão novo e a importação dos "
            "totais das faturas informados. Exige nome, instituição se conhecida, limite, dias "
            "de fechamento e vencimento; cada mês de fatura informado significa o mês do "
            "vencimento, e o Finance Engine calcula o ciclo que fecha antes dele. Nunca deduza "
            "termos ausentes. Importa apenas totais "
            "mensais, sem criar compras nem despesas históricas."
        ),
        CreateCreditCardWithInvoicesInput,
        _create_credit_card_with_invoices_preview,
        requires_confirmation=True,
        confirmed_handler=_create_credit_card_with_invoices,
    ),
    ToolDefinition(
        "create_card_purchase",
        "Registra uma compra já feita em cartão de crédito.",
        CreateCardPurchaseInput,
        _create_card_purchase,
    ),
    ToolDefinition(
        "set_card_invoice_opening_balances",
        (
            "Importa o total atual de uma ou mais faturas que já existem. Converte o total em "
            "saldo inicial da dívida, descontando compras daquela fatura que já estejam "
            "registradas para evitar duplicá-las. Informe o mês do vencimento da fatura; o "
            "Finance Engine calcula automaticamente o ciclo conforme os dias do cartão. Não "
            "gera compras nem despesas históricas. Use os valores totais e meses exatos "
            "informados; sempre exige confirmação. "
            "Não use para registrar compras novas já feitas."
        ),
        SetInvoiceOpeningBalancesInput,
        _card_invoice_opening_balance_preview,
        requires_confirmation=True,
        confirmed_handler=_set_card_invoice_opening_balances,
    ),
    ToolDefinition(
        "create_recurrence",
        (
            "Agenda um compromisso financeiro FUTURO, nunca um movimento já pago. "
            "Sempre apresenta prévia e exige confirmação explícita. Use para programar um gasto "
            "fixo/recorrente com datas e frequência. Escolha conta e categoria retornadas por "
            "get_accounts/get_categories; se houver mais de uma conta compatível, pergunte. "
            "Pix é a forma de pagamento, não uma conta; anote em notes. Envie amount como texto "
            "decimal exato e starts_on/ends_on como datas YYYY-MM-DD; o fim é inclusivo. "
            "Ocorrências previstas não alteram saldo ou despesas até serem marcadas como pagas."
        ),
        CreateRecurrenceInput,
        _recurrence_preview,
        requires_confirmation=True,
        confirmed_handler=_create_recurrence,
    ),
    ToolDefinition(
        "create_transfer",
        "Registra uma transferência própria já realizada entre contas.",
        CreateTransferInput,
        _create_transfer,
    ),
    ToolDefinition(
        "get_dashboard_summary",
        (
            "Consulta saldos por tipo, incluindo somente contas correntes no saldo principal, "
            "além dos saldos projetados e da previsão de contas a pagar até o fim do mês atual. "
            "Use para saldo disponível e obrigações do mês atual; para previsão de outro mês, "
            "use get_month_forecast."
        ),
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


def tool_schemas(allowed_names: set[str] | None = None) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "name": definition.name,
            "description": definition.description,
            "parameters": _call_args(definition.input_model.model_json_schema()),
            "strict": True,
        }
        for definition in TOOL_DEFINITIONS
        if allowed_names is None or definition.name in allowed_names
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


def _post_movement_account_card(
    name: str,
    result: object,
    previous_account_ids: set[UUID],
    user: User,
    db: Session,
) -> dict[str, object] | None:
    """Return Finance Engine balances recalculated after a successful account movement."""
    account_ids = set(previous_account_ids)
    result_data = _serialize(result)
    if isinstance(result_data, dict):
        fields = (
            ("source_account_id", "destination_account_id")
            if name == "create_transfer"
            else ("account_id",)
        )
        for field in fields:
            value = result_data.get(field)
            if isinstance(value, str):
                try:
                    account_ids.add(UUID(value))
                except ValueError:
                    continue

    if not account_ids:
        return None

    accounts = [
        account
        for account in list_accounts(user, db, include_archived=True)
        if account.id in account_ids
    ]
    if not accounts:
        return None
    return {
        "type": "account_card",
        "data": _serialize(accounts),
        "snapshot_kind": "after_movement",
    }


def execute_finance_tool(
    name: str,
    arguments: object,
    user: User,
    db: Session,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
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
        previous_account_ids: set[UUID] = set()
        if name == "update_transaction" and confirmed:
            transaction_id = input_data.get("transaction_id")
            if isinstance(transaction_id, str):
                try:
                    transaction_uuid = UUID(transaction_id)
                except ValueError:
                    transaction_uuid = None
                if transaction_uuid is not None:
                    previous_account_id = db.scalar(
                        select(Transaction.account_id).where(
                            Transaction.id == transaction_uuid,
                            Transaction.user_id == user.id,
                        )
                    )
                    if previous_account_id is not None:
                        previous_account_ids.add(previous_account_id)
        handler = definition.confirmed_handler if confirmed else None
        selected_handler = handler or definition.handler
        if name in {"create_transaction", "create_transfer", "create_card_purchase"}:
            idempotent_handler = cast(Callable[..., tuple[object, str | None]], selected_handler)
            result, card_type = idempotent_handler(
                db, user, payload, idempotency_key=idempotency_key
            )
        else:
            result, card_type = selected_handler(db, user, payload)
        serialized = _serialize(result)
        cards: list[dict[str, object]] = []
        if card_type is not None:
            cards.append({"type": card_type, "data": serialized})
        if name in {"create_transaction", "update_transaction", "create_transfer"}:
            account_card = _post_movement_account_card(
                name, result, previous_account_ids, user, db
            )
            if account_card is not None:
                cards.append(account_card)
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

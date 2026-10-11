from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[1]:
            raise ValueError("Informe um e-mail válido.")
        return normalized


class SetupRequest(Credentials):
    display_name: str = Field(min_length=1, max_length=100)
    bootstrap_token: str | None = Field(default=None, min_length=32, max_length=256)
    totp_code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe seu nome.")
        return normalized


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str


class SetupStateResponse(BaseModel):
    requires_setup: bool
    setup_available: bool
    bootstrap_token_required: bool
    mfa_required: bool


class LoginRequest(Credentials):
    totp_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class LoginCheckResponse(BaseModel):
    mfa_required: bool
    mfa_enrolled: bool
    mfa_enrollment_available: bool


class MFAEnrollmentRequest(Credentials):
    enrollment_token: str = Field(min_length=32, max_length=256)


class MFAEnrollmentConfirmRequest(MFAEnrollmentRequest):
    totp_code: str = Field(pattern=r"^\d{6}$")


class MFAEnrollmentResponse(BaseModel):
    qr_code_data_url: str
    manual_key: str
    expires_at: datetime


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["CHECKING", "SAVINGS", "CASH", "OTHER"]
    currency: Literal["BRL"] = "BRL"
    opening_balance: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    opening_balance_date: date | None = None

    @model_validator(mode="after")
    def require_balance_and_date_together(self) -> AccountCreate:
        if (self.opening_balance is None) != (self.opening_balance_date is None):
            raise ValueError("Informe o saldo inicial e sua data, ou deixe os dois em branco.")
        return self

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome da conta.")
        return normalized

    @field_validator("opening_balance", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: Literal["CHECKING", "SAVINGS", "CASH", "OTHER"] | None = None
    opening_balance: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    opening_balance_date: date | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome da conta.")
        return normalized

    @field_validator("opening_balance", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class AccountResponse(BaseModel):
    id: UUID
    name: str
    type: str
    currency: str
    opening_balance: Decimal | None
    opening_balance_date: date | None
    is_active: bool
    balance: Decimal | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("opening_balance", "balance")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return format(value, ".2f") if value is not None else None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["INCOME", "EXPENSE"]

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome da categoria.")
        return normalized


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: Literal["INCOME", "EXPENSE"] | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome da categoria.")
        return normalized


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    type: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class CreditCardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    institution: str | None = Field(default=None, max_length=100)
    credit_limit: Decimal = Field(ge=Decimal("0"), max_digits=14, decimal_places=2)
    closing_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)

    @field_validator("name")
    @classmethod
    def normalize_card_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome do cartão.")
        return normalized

    @field_validator("institution")
    @classmethod
    def normalize_institution(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("credit_limit", mode="before")
    @classmethod
    def require_exact_card_limit_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class CreditCardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    institution: str | None = Field(default=None, max_length=100)
    credit_limit: Decimal | None = Field(
        default=None, ge=Decimal("0"), max_digits=14, decimal_places=2
    )
    closing_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)

    @field_validator("name")
    @classmethod
    def normalize_card_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome do cartão.")
        return normalized

    @field_validator("institution")
    @classmethod
    def normalize_institution(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("credit_limit", mode="before")
    @classmethod
    def require_exact_card_limit_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class CreditCardResponse(BaseModel):
    id: UUID
    name: str
    institution: str | None
    credit_limit: Decimal
    currency: str
    closing_day: int
    due_day: int
    is_active: bool
    used_limit: Decimal
    available_limit: Decimal
    next_due_date: date | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("credit_limit", "used_limit", "available_limit")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class TransferCreate(BaseModel):
    source_account_id: UUID
    destination_account_id: UUID
    amount: Decimal = Field(gt=Decimal("0"), max_digits=14, decimal_places=2)
    occurred_at: date
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if not isinstance(value, (str, Decimal)):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CardPurchaseCreate(BaseModel):
    credit_card_id: UUID
    category_id: UUID
    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=Decimal("0"), max_digits=14, decimal_places=2)
    occurred_at: date
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe a descrição da compra.")
        return normalized

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if not isinstance(value, (str, Decimal)):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CardPaymentCreate(BaseModel):
    account_id: UUID
    amount: Decimal = Field(gt=Decimal("0"), max_digits=14, decimal_places=2)
    occurred_at: date
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class TransactionCreate(BaseModel):
    account_id: UUID
    category_id: UUID
    type: Literal["INCOME", "EXPENSE"]
    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=Decimal("0"), max_digits=14, decimal_places=2)
    occurred_at: date
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe a descrição do lançamento.")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if not isinstance(value, (str, Decimal)):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class TransactionUpdate(BaseModel):
    account_id: UUID | None = None
    category_id: UUID | None = None
    type: Literal["INCOME", "EXPENSE"] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=14, decimal_places=2)
    occurred_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe a descrição do lançamento.")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, (str, Decimal)):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class TransactionResponse(BaseModel):
    id: UUID
    account_id: UUID | None
    category_id: UUID | None
    category_name: str | None
    source_account_id: UUID | None
    destination_account_id: UUID | None
    invoice_id: UUID | None
    credit_card_id: UUID | None
    credit_card_name: str | None
    type: Literal["INCOME", "EXPENSE", "TRANSFER", "CARD_PURCHASE", "CARD_PAYMENT"]
    source: str
    status: str
    description: str
    amount: Decimal
    occurred_at: date
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("amount")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class CategoryExpenseSummary(BaseModel):
    category_id: UUID
    category_name: str
    amount: Decimal

    @field_serializer("amount")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class DashboardSummary(BaseModel):
    as_of: date
    period_start: date
    period_end: date
    total_balance: Decimal | None
    incomplete_account_count: int
    monthly_income: Decimal
    monthly_expenses: Decimal
    monthly_result: Decimal
    expenses_by_category: list[CategoryExpenseSummary]
    cards: list[CreditCardResponse]
    recent_transactions: list[TransactionResponse]

    @field_serializer("total_balance", "monthly_income", "monthly_expenses", "monthly_result")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return format(value, ".2f") if value is not None else None


class CardInvoiceResponse(BaseModel):
    id: UUID
    credit_card_id: UUID
    credit_card_name: str
    period_start: date
    period_end: date
    closing_date: date
    due_date: date
    opening_balance: Decimal
    total: Decimal
    paid_amount: Decimal
    outstanding: Decimal
    status: Literal["OPEN", "CLOSED", "PARTIALLY_PAID", "PAID", "OVERDUE"]
    purchases: list[TransactionResponse]
    payments: list[TransactionResponse]

    @field_serializer("opening_balance", "total", "paid_amount", "outstanding")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class CardInvoiceOpeningBalanceSet(BaseModel):
    closing_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount: Decimal = Field(ge=Decimal("0"), max_digits=14, decimal_places=2)

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if not isinstance(value, (str, Decimal)):
            raise ValueError("Informe o valor da fatura como texto decimal.")
        return value


class RecurrenceCreate(BaseModel):
    account_id: UUID
    category_id: UUID
    type: Literal["INCOME", "EXPENSE"]
    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=Decimal("0"), max_digits=14, decimal_places=2)
    frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "YEARLY"] = "MONTHLY"
    interval: int = Field(default=1, ge=1, le=365)
    starts_on: date
    ends_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe a descrição da recorrência.")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if not isinstance(value, (str, Decimal)):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class RecurrenceUpdate(BaseModel):
    account_id: UUID | None = None
    category_id: UUID | None = None
    type: Literal["INCOME", "EXPENSE"] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=14, decimal_places=2)
    frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "YEARLY"] | None = None
    interval: int | None = Field(default=None, ge=1, le=365)
    starts_on: date | None = None
    ends_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe a descrição da recorrência.")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, (str, Decimal)):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class RecurrenceOccurrenceUpdate(BaseModel):
    scope: Literal["THIS", "THIS_AND_FUTURE", "ENTIRE_RULE"] = "THIS"
    account_id: UUID | None = None
    category_id: UUID | None = None
    type: Literal["INCOME", "EXPENSE"] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Decimal | None = Field(default=None, gt=Decimal("0"), max_digits=14, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe a descrição da ocorrência.")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("amount", mode="before")
    @classmethod
    def require_exact_money_string(cls, value: object) -> object:
        if value is not None and not isinstance(value, (str, Decimal)):
            raise ValueError("Informe valores monetários como texto decimal.")
        return value


class RecurrenceResponse(BaseModel):
    id: UUID
    account_id: UUID
    category_id: UUID
    type: Literal["INCOME", "EXPENSE"]
    description: str
    amount: Decimal
    currency: Literal["BRL"]
    frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "YEARLY"]
    interval: int
    starts_on: date
    ends_on: date | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("amount")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class RecurrenceOccurrenceResponse(BaseModel):
    id: UUID
    rule_id: UUID
    transaction_id: UUID | None
    account_id: UUID
    category_id: UUID
    type: Literal["INCOME", "EXPENSE"]
    description: str
    amount: Decimal
    due_date: date
    notes: str | None
    status: Literal["PLANNED", "PENDING", "OVERDUE", "PAID", "SKIPPED", "CANCELLED"]

    @field_serializer("amount")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")

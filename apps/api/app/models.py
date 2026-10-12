from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_totp_counter: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avatar_revision: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    avatar_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    mfa_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_enrollment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    accounts: Mapped[list["Account"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    categories: Mapped[list["Category"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    ai_conversations: Mapped[list["AIConversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    ai_memories: Mapped[list["AIMemory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user: Mapped[User] = relationship(back_populates="sessions")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_accounts_id_user_id"),
        CheckConstraint(
            "(opening_balance IS NULL AND opening_balance_date IS NULL) OR "
            "(opening_balance IS NOT NULL AND opening_balance_date IS NOT NULL)",
            name="ck_accounts_opening_balance_pair",
        ),
        CheckConstraint(
            "type IN ('CHECKING', 'SAVINGS', 'CASH', 'OTHER')", name="ck_accounts_type"
        ),
        CheckConstraint("currency = 'BRL'", name="ck_accounts_currency_brl"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    opening_balance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    user: Mapped[User] = relationship(back_populates="accounts")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_categories_id_user_id"),
        CheckConstraint("type IN ('INCOME', 'EXPENSE')", name="ck_categories_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    user: Mapped[User] = relationship(back_populates="categories")


class CreditCard(Base):
    __tablename__ = "credit_cards"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_credit_cards_id_user_id"),
        ForeignKeyConstraint(
            ["payment_account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_credit_cards_payment_account_owner",
        ),
        CheckConstraint("currency = 'BRL'", name="ck_credit_cards_currency_brl"),
        CheckConstraint("credit_limit >= 0", name="ck_credit_cards_limit_nonnegative"),
        CheckConstraint("closing_day BETWEEN 1 AND 31", name="ck_credit_cards_closing_day"),
        CheckConstraint("due_day BETWEEN 1 AND 31", name="ck_credit_cards_due_day"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    closing_day: Mapped[int] = mapped_column(nullable=False)
    due_day: Mapped[int] = mapped_column(nullable=False)
    payment_account_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CardInvoice(Base):
    __tablename__ = "card_invoices"
    __table_args__ = (
        Index("ix_card_invoices_user_due_date", "user_id", "due_date"),
        UniqueConstraint("id", "user_id", name="uq_card_invoices_id_user_id"),
        UniqueConstraint(
            "credit_card_id", "user_id", "closing_date", name="uq_card_invoice_card_cycle"
        ),
        ForeignKeyConstraint(
            ["credit_card_id", "user_id"],
            ["credit_cards.id", "credit_cards.user_id"],
            ondelete="RESTRICT",
            name="fk_card_invoices_card_owner",
        ),
        CheckConstraint("period_start <= period_end", name="ck_card_invoices_period_order"),
        CheckConstraint("period_end = closing_date", name="ck_card_invoices_closing_period_end"),
        CheckConstraint("due_date > closing_date", name="ck_card_invoices_due_after_close"),
        CheckConstraint(
            "opening_balance >= 0",
            name="ck_card_invoices_opening_balance_nonnegative",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    credit_card_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    closing_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (UniqueConstraint("id", "user_id", name="uq_ai_conversations_id_user_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="Nova conversa")
    title_is_custom: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    title_generated_for_message_count: Mapped[int] = mapped_column(
        default=0, server_default="0", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    user: Mapped[User] = relationship(back_populates="ai_conversations")
    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AIMessage.created_at"
    )


class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_ai_messages_id_user_id"),
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["ai_conversations.id", "ai_conversations.user_id"],
            ondelete="CASCADE",
            name="fk_ai_messages_conversation_owner",
        ),
        CheckConstraint(
            "role IN ('USER', 'ASSISTANT', 'TOOL', 'SYSTEM')", name="ck_ai_messages_role"
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_messages_input_tokens"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_messages_output_tokens"
        ),
        CheckConstraint(
            "cached_input_tokens IS NULL OR cached_input_tokens >= 0",
            name="ck_ai_messages_cached_input_tokens",
        ),
        CheckConstraint(
            "cache_write_tokens IS NULL OR cache_write_tokens >= 0",
            name="ck_ai_messages_cache_write_tokens",
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_ai_messages_duration"),
        CheckConstraint(
            "diagnostic_status IS NULL OR diagnostic_status IN "
            "('SUCCEEDED', 'FAILED', 'PENDING_CONFIRMATION')",
            name="ck_ai_messages_diagnostic_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured_content: Mapped[dict[str, object] | list[object] | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    diagnostic_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    diagnostic_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    conversation: Mapped[AIConversation] = relationship(back_populates="messages")


class AIToolCall(Base):
    __tablename__ = "ai_tool_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["ai_conversations.id", "ai_conversations.user_id"],
            ondelete="CASCADE",
            name="fk_ai_tool_calls_conversation_owner",
        ),
        ForeignKeyConstraint(
            ["message_id", "user_id"],
            ["ai_messages.id", "ai_messages.user_id"],
            ondelete="CASCADE",
            name="fk_ai_tool_calls_message_owner",
        ),
        CheckConstraint(
            "status IN ('PENDING_CONFIRMATION', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_ai_tool_calls_status",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_ai_tool_calls_duration"
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_tool_calls_input_tokens"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_tool_calls_output_tokens"
        ),
        CheckConstraint(
            "cached_input_tokens IS NULL OR cached_input_tokens >= 0",
            name="ck_ai_tool_calls_cached_input_tokens",
        ),
        CheckConstraint(
            "cache_write_tokens IS NULL OR cache_write_tokens >= 0",
            name="ck_ai_tool_calls_cache_write_tokens",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    message_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_sanitized: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    output_sanitized: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    diagnostic_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIMemory(Base):
    __tablename__ = "ai_memories"
    __table_args__ = (
        CheckConstraint("kind = 'PREFERENCE'", name="ck_ai_memories_kind"),
        CheckConstraint("length(content) BETWEEN 1 AND 500", name="ck_ai_memories_content_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="PREFERENCE")
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user: Mapped[User] = relationship(back_populates="ai_memories")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_user_occurred_at", "user_id", "occurred_at"),
        Index("ix_transactions_account_occurred_at", "account_id", "occurred_at"),
        Index("ix_transactions_category_id", "category_id"),
        Index("ix_transactions_source_account_occurred_at", "source_account_id", "occurred_at"),
        Index(
            "ix_transactions_destination_account_occurred_at",
            "destination_account_id",
            "occurred_at",
        ),
        Index("ix_transactions_user_invoice_type", "user_id", "card_invoice_id", "type"),
        UniqueConstraint("id", "user_id", name="uq_transactions_id_user_id"),
        UniqueConstraint(
            "user_id", "idempotency_operation", "idempotency_key",
            name="uq_transactions_user_idempotency_operation_key",
        ),
        CheckConstraint(
            "(idempotency_operation IS NULL AND idempotency_key IS NULL "
            "AND idempotency_fingerprint IS NULL) OR "
            "(idempotency_operation IS NOT NULL AND idempotency_key IS NOT NULL "
            "AND idempotency_fingerprint IS NOT NULL)",
            name="ck_transactions_idempotency_fields_complete",
        ),
        CheckConstraint(
            "type IN ('INCOME', 'EXPENSE', 'TRANSFER', 'CARD_PURCHASE', 'CARD_PAYMENT')",
            name="ck_transactions_type",
        ),
        CheckConstraint("source = 'MANUAL'", name="ck_transactions_source_manual"),
        CheckConstraint("status = 'CONFIRMED'", name="ck_transactions_status_confirmed"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "(type IN ('INCOME', 'EXPENSE') AND account_id IS NOT NULL "
            "AND category_id IS NOT NULL AND source_account_id IS NULL "
            "AND destination_account_id IS NULL AND card_invoice_id IS NULL) "
            "OR (type = 'TRANSFER' AND account_id IS NULL AND category_id IS NULL "
            "AND source_account_id IS NOT NULL AND destination_account_id IS NOT NULL "
            "AND source_account_id <> destination_account_id AND card_invoice_id IS NULL) "
            "OR (type = 'CARD_PURCHASE' AND account_id IS NULL AND category_id IS NOT NULL "
            "AND source_account_id IS NULL AND destination_account_id IS NULL "
            "AND card_invoice_id IS NOT NULL) "
            "OR (type = 'CARD_PAYMENT' AND account_id IS NOT NULL AND category_id IS NULL "
            "AND source_account_id IS NULL AND destination_account_id IS NULL "
            "AND card_invoice_id IS NOT NULL)",
            name="ck_transactions_type_references",
        ),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_transactions_account_owner",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            ondelete="RESTRICT",
            name="fk_transactions_category_owner",
        ),
        ForeignKeyConstraint(
            ["source_account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_transactions_source_account_owner",
        ),
        ForeignKeyConstraint(
            ["destination_account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_transactions_destination_account_owner",
        ),
        ForeignKeyConstraint(
            ["card_invoice_id", "user_id"],
            ["card_invoices.id", "card_invoices.user_id"],
            ondelete="RESTRICT",
            name="fk_transactions_card_invoice_owner",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    category_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_account_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    destination_account_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    card_invoice_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="MANUAL")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="CONFIRMED")
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_operation: Mapped[str | None] = mapped_column(String(40), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RecurrenceRule(Base):
    __tablename__ = "recurrence_rules"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_recurrence_rules_id_user_id"),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_recurrence_rules_account_owner",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            ondelete="RESTRICT",
            name="fk_recurrence_rules_category_owner",
        ),
        CheckConstraint("type IN ('INCOME', 'EXPENSE')", name="ck_recurrence_rules_type"),
        CheckConstraint("amount > 0", name="ck_recurrence_rules_amount_positive"),
        CheckConstraint("currency = 'BRL'", name="ck_recurrence_rules_currency_brl"),
        CheckConstraint(
            "frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY')",
            name="ck_recurrence_rules_frequency",
        ),
        CheckConstraint("interval BETWEEN 1 AND 365", name="ck_recurrence_rules_interval"),
        CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on", name="ck_recurrence_rules_date_order"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    interval: Mapped[int] = mapped_column(nullable=False, default=1)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RecurrenceOccurrence(Base):
    __tablename__ = "recurrence_occurrences"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_recurrence_occurrences_id_user_id"),
        UniqueConstraint(
            "rule_id", "user_id", "due_date", name="uq_recurrence_occurrence_rule_date"
        ),
        UniqueConstraint("transaction_id", name="uq_recurrence_occurrence_transaction"),
        ForeignKeyConstraint(
            ["rule_id", "user_id"],
            ["recurrence_rules.id", "recurrence_rules.user_id"],
            ondelete="CASCADE",
            name="fk_recurrence_occurrences_rule_owner",
        ),
        ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            ondelete="RESTRICT",
            name="fk_recurrence_occurrences_transaction_owner",
        ),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_recurrence_occurrences_account_owner",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            ondelete="RESTRICT",
            name="fk_recurrence_occurrences_category_owner",
        ),
        CheckConstraint("type IN ('INCOME', 'EXPENSE')", name="ck_recurrence_occurrences_type"),
        CheckConstraint("amount > 0", name="ck_recurrence_occurrences_amount_positive"),
        CheckConstraint(
            "status IN ('PLANNED', 'PAID', 'SKIPPED', 'CANCELLED')",
            name="ck_recurrence_occurrences_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rule_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    transaction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PLANNED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlannedCommitment(Base):
    __tablename__ = "planned_commitments"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_planned_commitments_id_user_id"),
        UniqueConstraint("transaction_id", name="uq_planned_commitments_transaction"),
        ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            ondelete="RESTRICT",
            name="fk_planned_commitments_transaction_owner",
        ),
        ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_planned_commitments_account_owner",
        ),
        ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            ondelete="RESTRICT",
            name="fk_planned_commitments_category_owner",
        ),
        CheckConstraint("type IN ('INCOME', 'EXPENSE')", name="ck_planned_commitments_type"),
        CheckConstraint("amount > 0", name="ck_planned_commitments_amount_positive"),
        CheckConstraint(
            "status IN ('PLANNED', 'PAID', 'CANCELLED')", name="ck_planned_commitments_status"
        ),
        CheckConstraint(
            "(status = 'PAID' AND transaction_id IS NOT NULL) OR "
            "(status <> 'PAID' AND transaction_id IS NULL)",
            name="ck_planned_commitments_paid_transaction",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    transaction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PLANNED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

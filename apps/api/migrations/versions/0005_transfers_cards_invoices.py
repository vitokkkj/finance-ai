"""Adiciona transferências próprias, cartões e ciclos de fatura.

Revision ID: 0005_transfers_cards
Revises: 0004_transactions
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Uuid

revision: str = "0005_transfers_cards"
down_revision: str | None = "0004_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "credit_cards",
        sa.Column("id", Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("institution", sa.String(length=100), nullable=True),
        sa.Column("credit_limit", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("closing_day", sa.Integer(), nullable=False),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("currency = 'BRL'", name="ck_credit_cards_currency_brl"),
        sa.CheckConstraint("credit_limit >= 0", name="ck_credit_cards_limit_nonnegative"),
        sa.CheckConstraint("closing_day BETWEEN 1 AND 31", name="ck_credit_cards_closing_day"),
        sa.CheckConstraint("due_day BETWEEN 1 AND 31", name="ck_credit_cards_due_day"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_credit_cards_id_user_id"),
    )
    op.create_index("ix_credit_cards_user_id", "credit_cards", ["user_id"])

    op.create_table(
        "card_invoices",
        sa.Column("id", Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("credit_card_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("closing_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("period_start <= period_end", name="ck_card_invoices_period_order"),
        sa.CheckConstraint("period_end = closing_date", name="ck_card_invoices_closing_period_end"),
        sa.CheckConstraint("due_date > closing_date", name="ck_card_invoices_due_after_close"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["credit_card_id", "user_id"],
            ["credit_cards.id", "credit_cards.user_id"],
            ondelete="RESTRICT",
            name="fk_card_invoices_card_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_card_invoices_id_user_id"),
        sa.UniqueConstraint(
            "credit_card_id", "user_id", "closing_date", name="uq_card_invoice_card_cycle"
        ),
    )
    op.create_index("ix_card_invoices_user_due_date", "card_invoices", ["user_id", "due_date"])

    op.drop_constraint("ck_transactions_type", "transactions", type_="check")
    op.alter_column(
        "transactions",
        "type",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column("transactions", "account_id", existing_type=Uuid(as_uuid=True), nullable=True)
    op.alter_column("transactions", "category_id", existing_type=Uuid(as_uuid=True), nullable=True)
    op.add_column("transactions", sa.Column("source_account_id", Uuid(as_uuid=True), nullable=True))
    op.add_column(
        "transactions", sa.Column("destination_account_id", Uuid(as_uuid=True), nullable=True)
    )
    op.add_column("transactions", sa.Column("card_invoice_id", Uuid(as_uuid=True), nullable=True))
    op.create_check_constraint(
        "ck_transactions_type",
        "transactions",
        "type IN ('INCOME', 'EXPENSE', 'TRANSFER', 'CARD_PURCHASE', 'CARD_PAYMENT')",
    )
    op.create_check_constraint(
        "ck_transactions_type_references",
        "transactions",
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
    )
    op.create_foreign_key(
        "fk_transactions_source_account_owner",
        "transactions",
        "accounts",
        ["source_account_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_transactions_destination_account_owner",
        "transactions",
        "accounts",
        ["destination_account_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_transactions_card_invoice_owner",
        "transactions",
        "card_invoices",
        ["card_invoice_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_transactions_source_account_occurred_at",
        "transactions",
        ["source_account_id", "occurred_at"],
    )
    op.create_index(
        "ix_transactions_destination_account_occurred_at",
        "transactions",
        ["destination_account_id", "occurred_at"],
    )
    op.create_index(
        "ix_transactions_user_invoice_type", "transactions", ["user_id", "card_invoice_id", "type"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    transactions = sa.table("transactions", sa.column("type", sa.String()))
    unsupported_rows = bind.scalar(
        sa.select(sa.func.count())
        .select_from(transactions)
        .where(transactions.c.type.not_in(["INCOME", "EXPENSE"]))
    )
    if unsupported_rows:
        raise RuntimeError(
            "Não é seguro reverter a Fase 2B: há transferências ou movimentos de cartão."
        )

    op.drop_index("ix_transactions_user_invoice_type", table_name="transactions")
    op.drop_index("ix_transactions_destination_account_occurred_at", table_name="transactions")
    op.drop_index("ix_transactions_source_account_occurred_at", table_name="transactions")
    op.drop_constraint("fk_transactions_card_invoice_owner", "transactions", type_="foreignkey")
    op.drop_constraint(
        "fk_transactions_destination_account_owner", "transactions", type_="foreignkey"
    )
    op.drop_constraint("fk_transactions_source_account_owner", "transactions", type_="foreignkey")
    op.drop_constraint("ck_transactions_type_references", "transactions", type_="check")
    op.drop_constraint("ck_transactions_type", "transactions", type_="check")
    op.alter_column(
        "transactions",
        "type",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_transactions_type",
        "transactions",
        "type IN ('INCOME', 'EXPENSE')",
    )
    op.drop_column("transactions", "card_invoice_id")
    op.drop_column("transactions", "destination_account_id")
    op.drop_column("transactions", "source_account_id")
    op.alter_column("transactions", "category_id", existing_type=Uuid(as_uuid=True), nullable=False)
    op.alter_column("transactions", "account_id", existing_type=Uuid(as_uuid=True), nullable=False)
    op.drop_index("ix_card_invoices_user_due_date", table_name="card_invoices")
    op.drop_table("card_invoices")
    op.drop_index("ix_credit_cards_user_id", table_name="credit_cards")
    op.drop_table("credit_cards")

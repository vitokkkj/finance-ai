"""Cria os lançamentos manuais e restringe referências ao mesmo usuário.

Revision ID: 0004_transactions
Revises: 0003_categories
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Uuid

revision: str = "0004_transactions"
down_revision: str | None = "0003_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_accounts_id_user_id", "accounts", ["id", "user_id"])
    op.create_unique_constraint("uq_categories_id_user_id", "categories", ["id", "user_id"])
    op.create_table(
        "transactions",
        sa.Column("id", Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("category_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("type IN ('INCOME', 'EXPENSE')", name="ck_transactions_type"),
        sa.CheckConstraint("source = 'MANUAL'", name="ck_transactions_source_manual"),
        sa.CheckConstraint("status = 'CONFIRMED'", name="ck_transactions_status_confirmed"),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_transactions_account_owner",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            ondelete="RESTRICT",
            name="fk_transactions_category_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transactions_user_occurred_at", "transactions", ["user_id", "occurred_at"]
    )
    op.create_index(
        "ix_transactions_account_occurred_at", "transactions", ["account_id", "occurred_at"]
    )
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_category_id", table_name="transactions")
    op.drop_index("ix_transactions_account_occurred_at", table_name="transactions")
    op.drop_index("ix_transactions_user_occurred_at", table_name="transactions")
    op.drop_table("transactions")
    op.drop_constraint("uq_categories_id_user_id", "categories", type_="unique")
    op.drop_constraint("uq_accounts_id_user_id", "accounts", type_="unique")

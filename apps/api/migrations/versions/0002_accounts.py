"""Cria as contas financeiras manuais.

Revision ID: 0002_accounts
Revises: 0001_users_sessions
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Uuid

revision: str = "0002_accounts"
down_revision: str | None = "0001_users_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("opening_balance", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("opening_balance_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "type IN ('CHECKING', 'SAVINGS', 'CASH', 'OTHER')", name="ck_accounts_type"
        ),
        sa.CheckConstraint("currency = 'BRL'", name="ck_accounts_currency_brl"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_user_id", "accounts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_accounts_user_id", table_name="accounts")
    op.drop_table("accounts")

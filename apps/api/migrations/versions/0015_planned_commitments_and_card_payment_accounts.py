"""Add planned commitments and card payment accounts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_planned_commitments"
down_revision: str | None = "0014_conversation_titles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credit_cards", sa.Column("payment_account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_credit_cards_payment_account_owner",
        "credit_cards",
        "accounts",
        ["payment_account_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "planned_commitments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            ondelete="RESTRICT",
            name="fk_planned_commitments_transaction_owner",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            ondelete="RESTRICT",
            name="fk_planned_commitments_account_owner",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            ondelete="RESTRICT",
            name="fk_planned_commitments_category_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_planned_commitments_id_user_id"),
        sa.UniqueConstraint("transaction_id", name="uq_planned_commitments_transaction"),
        sa.CheckConstraint("type IN ('INCOME', 'EXPENSE')", name="ck_planned_commitments_type"),
        sa.CheckConstraint("amount > 0", name="ck_planned_commitments_amount_positive"),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'PAID', 'CANCELLED')", name="ck_planned_commitments_status"
        ),
        sa.CheckConstraint(
            "(status = 'PAID' AND transaction_id IS NOT NULL) OR "
            "(status <> 'PAID' AND transaction_id IS NULL)",
            name="ck_planned_commitments_paid_transaction",
        ),
    )
    op.create_index("ix_planned_commitments_user_id", "planned_commitments", ["user_id"])
    op.create_index("ix_planned_commitments_due_date", "planned_commitments", ["due_date"])


def downgrade() -> None:
    op.drop_index("ix_planned_commitments_due_date", table_name="planned_commitments")
    op.drop_index("ix_planned_commitments_user_id", table_name="planned_commitments")
    op.drop_table("planned_commitments")
    op.drop_constraint("fk_credit_cards_payment_account_owner", "credit_cards", type_="foreignkey")
    op.drop_column("credit_cards", "payment_account_id")

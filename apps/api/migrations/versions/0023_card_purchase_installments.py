"""Represent card purchase installments on their invoice transactions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_card_purchase_installments"
down_revision: str | None = "0022_ai_latency_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("installment_group_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("installment_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column("installment_count", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_transactions_installment_fields",
        "transactions",
        "(installment_group_id IS NULL AND installment_number IS NULL "
        "AND installment_count IS NULL) OR "
        "(installment_group_id IS NOT NULL AND type = 'CARD_PURCHASE' "
        "AND installment_number IS NOT NULL AND installment_count IS NOT NULL "
        "AND installment_number BETWEEN 1 AND installment_count "
        "AND installment_count BETWEEN 2 AND 36)",
    )
    op.create_unique_constraint(
        "uq_transactions_installment_group_number",
        "transactions",
        ["user_id", "installment_group_id", "installment_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_transactions_installment_group_number", "transactions", type_="unique"
    )
    op.drop_constraint("ck_transactions_installment_fields", "transactions", type_="check")
    op.drop_column("transactions", "installment_count")
    op.drop_column("transactions", "installment_number")
    op.drop_column("transactions", "installment_group_id")

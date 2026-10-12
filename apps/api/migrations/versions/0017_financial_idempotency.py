"""Persist idempotency keys for manual financial movements."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_financial_idempotency"
down_revision: str | None = "0016_totp_replay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("idempotency_operation", sa.String(40), nullable=True))
    op.add_column("transactions", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.add_column(
        "transactions", sa.Column("idempotency_fingerprint", sa.String(64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_transactions_user_idempotency_operation_key",
        "transactions",
        ["user_id", "idempotency_operation", "idempotency_key"],
    )
    op.create_check_constraint(
        "ck_transactions_idempotency_fields_complete",
        "transactions",
        "(idempotency_operation IS NULL AND idempotency_key IS NULL "
        "AND idempotency_fingerprint IS NULL) OR "
        "(idempotency_operation IS NOT NULL AND idempotency_key IS NOT NULL "
        "AND idempotency_fingerprint IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_transactions_idempotency_fields_complete", "transactions", type_="check"
    )
    op.drop_constraint(
        "uq_transactions_user_idempotency_operation_key", "transactions", type_="unique"
    )
    op.drop_column("transactions", "idempotency_fingerprint")
    op.drop_column("transactions", "idempotency_key")
    op.drop_column("transactions", "idempotency_operation")

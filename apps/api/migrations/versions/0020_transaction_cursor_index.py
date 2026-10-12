"""Index the transaction keyset pagination order."""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_transaction_cursor_index"
down_revision: str | None = "0019_managed_user_totp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_transactions_user_cursor",
        "transactions",
        ["user_id", "occurred_at", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_user_cursor", table_name="transactions")

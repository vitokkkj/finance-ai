"""Retain financial idempotency records after movement deletion."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_idempotency_tombstones"
down_revision: str | None = "0017_financial_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_idempotency_records",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("original_transaction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 16 AND 255",
            name="ck_financial_idempotency_key_length",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_financial_idempotency_fingerprint_length",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "user_id", "operation", "idempotency_key", name="pk_financial_idempotency_records"
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO financial_idempotency_records (
                user_id,
                operation,
                idempotency_key,
                request_fingerprint,
                original_transaction_id,
                created_at
            )
            SELECT
                user_id,
                idempotency_operation,
                idempotency_key,
                idempotency_fingerprint,
                id,
                created_at
            FROM transactions
            WHERE idempotency_key IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado: a versão antiga não preserva chaves de idempotência de movimentos "
        "excluídos. Restaure um backup validado em vez de remover os tombstones."
    )

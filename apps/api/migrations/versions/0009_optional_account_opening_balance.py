"""Permite cadastrar uma conta antes de conhecer o saldo inicial."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_optional_opening_balance"
down_revision: str | None = "0008_recurring_occurrences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column(
            "opening_balance",
            existing_type=sa.Numeric(precision=14, scale=2),
            nullable=True,
        )
        batch_op.alter_column(
            "opening_balance_date",
            existing_type=sa.Date(),
            nullable=True,
        )
        batch_op.create_check_constraint(
            "ck_accounts_opening_balance_pair",
            "(opening_balance IS NULL AND opening_balance_date IS NULL) OR "
            "(opening_balance IS NOT NULL AND opening_balance_date IS NOT NULL)",
        )


def downgrade() -> None:
    connection = op.get_bind()
    unknown_accounts = connection.execute(
        sa.text(
            "SELECT count(*) FROM accounts "
            "WHERE opening_balance IS NULL OR opening_balance_date IS NULL"
        )
    ).scalar_one()
    if unknown_accounts:
        raise RuntimeError(
            "Não é possível reverter: existem contas sem saldo inicial informado. "
            "Preencha os saldos antes de remover esta migration."
        )

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_constraint("ck_accounts_opening_balance_pair", type_="check")
        batch_op.alter_column(
            "opening_balance",
            existing_type=sa.Numeric(precision=14, scale=2),
            nullable=False,
        )
        batch_op.alter_column(
            "opening_balance_date",
            existing_type=sa.Date(),
            nullable=False,
        )

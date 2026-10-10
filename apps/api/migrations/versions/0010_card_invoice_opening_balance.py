"""Permite registrar saldo de fatura que já existia antes do uso da SophIA."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_card_invoice_open_balance"
down_revision: str | None = "0009_optional_opening_balance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "card_invoices",
        sa.Column(
            "opening_balance",
            sa.Numeric(precision=14, scale=2),
            server_default="0.00",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_card_invoices_opening_balance_nonnegative",
        "card_invoices",
        "opening_balance >= 0",
    )


def downgrade() -> None:
    connection = op.get_bind()
    imported_balances = connection.scalar(
        sa.text("SELECT count(*) FROM card_invoices WHERE opening_balance > 0")
    )
    if imported_balances:
        raise RuntimeError(
            "Não é seguro reverter: existem saldos iniciais de fatura registrados."
        )
    op.drop_constraint(
        "ck_card_invoices_opening_balance_nonnegative", "card_invoices", type_="check"
    )
    op.drop_column("card_invoices", "opening_balance")

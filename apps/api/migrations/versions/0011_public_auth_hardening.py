"""Revoga sessões anteriores à adoção do cookie seguro e do segundo fator."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_public_auth_hardening"
down_revision: str | None = "0010_card_invoice_open_balance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM auth_sessions"))


def downgrade() -> None:
    # Sessões expiradas ou revogadas não podem ser recriadas com segurança.
    pass

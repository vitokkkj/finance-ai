"""Store pending TOTP replacement secrets until the new code is confirmed."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_mfa_pending_secret"
down_revision: str | None = "0020_transaction_cursor_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_pending_secret_encrypted", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado: remover segredos TOTP pendentes poderia interromper uma troca "
        "em andamento. Restaure o backup validado junto com a versão anterior."
    )

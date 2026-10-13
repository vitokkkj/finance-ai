"""Store per-user MFA secrets for managed accounts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_managed_user_totp"
down_revision: str | None = "0018_idempotency_tombstones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_secret_encrypted", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade bloqueado: remover os segredos TOTP criptografados bloquearia as contas "
        "gerenciadas. Reimplante uma versão compatível em vez de apagar a coluna."
    )

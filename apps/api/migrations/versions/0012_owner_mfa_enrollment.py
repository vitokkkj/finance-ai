"""Registra o pareamento MFA do proprietário e seu prazo temporário."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_owner_mfa_enrollment"
down_revision: str | None = "0011_public_auth_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("mfa_enrollment_expires_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "mfa_enrollment_expires_at")
    op.drop_column("users", "mfa_enrolled_at")

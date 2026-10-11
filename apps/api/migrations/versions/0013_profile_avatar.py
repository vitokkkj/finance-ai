"""Armazena foto de perfil otimizada e vinculada à conta."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_profile_avatar"
down_revision: str | None = "0012_owner_mfa_enrollment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_revision", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("avatar_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_data")
    op.drop_column("users", "avatar_revision")

"""Track consumed authenticator counters to reject TOTP replay."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_totp_replay"
down_revision: str | None = "0015_planned_commitments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_totp_counter", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_totp_counter")

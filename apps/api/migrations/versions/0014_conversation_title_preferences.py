"""Preserva renomeações manuais de conversas."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_conversation_title_preferences"
down_revision: str | None = "0013_profile_avatar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_conversations",
        sa.Column("title_is_custom", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "ai_conversations",
        sa.Column(
            "title_generated_for_message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_conversations", "title_generated_for_message_count")
    op.drop_column("ai_conversations", "title_is_custom")

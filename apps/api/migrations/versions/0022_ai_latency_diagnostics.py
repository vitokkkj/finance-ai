"""Record first-output latency and tool schema count for AI responses."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_ai_latency_diagnostics"
down_revision: str | None = "0021_mfa_pending_secret"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_messages", sa.Column("preparation_ms", sa.Integer(), nullable=True))
    op.add_column("ai_messages", sa.Column("first_output_ms", sa.Integer(), nullable=True))
    op.add_column("ai_messages", sa.Column("first_text_ms", sa.Integer(), nullable=True))
    op.add_column("ai_messages", sa.Column("available_tool_count", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_ai_messages_preparation_duration",
        "ai_messages",
        "preparation_ms IS NULL OR preparation_ms >= 0",
    )
    op.create_check_constraint(
        "ck_ai_messages_first_output_duration",
        "ai_messages",
        "first_output_ms IS NULL OR first_output_ms >= 0",
    )
    op.create_check_constraint(
        "ck_ai_messages_first_text_duration",
        "ai_messages",
        "first_text_ms IS NULL OR first_text_ms >= 0",
    )
    op.create_check_constraint(
        "ck_ai_messages_available_tool_count",
        "ai_messages",
        "available_tool_count IS NULL OR available_tool_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ai_messages_available_tool_count", "ai_messages", type_="check"
    )
    op.drop_constraint("ck_ai_messages_first_text_duration", "ai_messages", type_="check")
    op.drop_constraint("ck_ai_messages_first_output_duration", "ai_messages", type_="check")
    op.drop_constraint("ck_ai_messages_preparation_duration", "ai_messages", type_="check")
    op.drop_column("ai_messages", "available_tool_count")
    op.drop_column("ai_messages", "first_text_ms")
    op.drop_column("ai_messages", "first_output_ms")
    op.drop_column("ai_messages", "preparation_ms")

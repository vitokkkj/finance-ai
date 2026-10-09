"""Adiciona dados de uso e diagnóstico do assistente."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_ai_diagnostics"
down_revision: str | None = "0006_ai_assistant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_messages", sa.Column("cached_input_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_messages", sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_messages", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column(
        "ai_messages", sa.Column("diagnostic_status", sa.String(length=24), nullable=True)
    )
    op.add_column(
        "ai_messages", sa.Column("diagnostic_error", sa.String(length=200), nullable=True)
    )
    op.create_check_constraint(
        "ck_ai_messages_cached_input_tokens",
        "ai_messages",
        "cached_input_tokens IS NULL OR cached_input_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_ai_messages_cache_write_tokens",
        "ai_messages",
        "cache_write_tokens IS NULL OR cache_write_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_ai_messages_duration",
        "ai_messages",
        "duration_ms IS NULL OR duration_ms >= 0",
    )
    op.create_check_constraint(
        "ck_ai_messages_diagnostic_status",
        "ai_messages",
        "diagnostic_status IS NULL OR diagnostic_status IN "
        "('SUCCEEDED', 'FAILED', 'PENDING_CONFIRMATION')",
    )

    op.add_column("ai_tool_calls", sa.Column("cached_input_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_tool_calls", sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "ai_tool_calls", sa.Column("diagnostic_error", sa.String(length=200), nullable=True)
    )
    op.create_check_constraint(
        "ck_ai_tool_calls_cached_input_tokens",
        "ai_tool_calls",
        "cached_input_tokens IS NULL OR cached_input_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_ai_tool_calls_cache_write_tokens",
        "ai_tool_calls",
        "cache_write_tokens IS NULL OR cache_write_tokens >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ai_tool_calls_cache_write_tokens", "ai_tool_calls", type_="check")
    op.drop_constraint("ck_ai_tool_calls_cached_input_tokens", "ai_tool_calls", type_="check")
    op.drop_column("ai_tool_calls", "diagnostic_error")
    op.drop_column("ai_tool_calls", "cache_write_tokens")
    op.drop_column("ai_tool_calls", "cached_input_tokens")

    op.drop_constraint("ck_ai_messages_diagnostic_status", "ai_messages", type_="check")
    op.drop_constraint("ck_ai_messages_duration", "ai_messages", type_="check")
    op.drop_constraint("ck_ai_messages_cache_write_tokens", "ai_messages", type_="check")
    op.drop_constraint("ck_ai_messages_cached_input_tokens", "ai_messages", type_="check")
    op.drop_column("ai_messages", "diagnostic_error")
    op.drop_column("ai_messages", "diagnostic_status")
    op.drop_column("ai_messages", "duration_ms")
    op.drop_column("ai_messages", "cache_write_tokens")
    op.drop_column("ai_messages", "cached_input_tokens")

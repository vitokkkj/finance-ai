"""Adiciona conversas, mensagens, auditoria de ferramentas e memórias explícitas."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Uuid

revision: str = "0006_ai_assistant"
down_revision: str | None = "0005_transfers_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_ai_conversations_id_user_id"),
    )
    op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"])

    op.create_table(
        "ai_messages",
        sa.Column("id", Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_content", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('USER', 'ASSISTANT', 'TOOL', 'SYSTEM')", name="ck_ai_messages_role"
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_messages_input_tokens"
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_messages_output_tokens"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["ai_conversations.id", "ai_conversations.user_id"],
            ondelete="CASCADE",
            name="fk_ai_messages_conversation_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_ai_messages_id_user_id"),
    )
    op.create_index("ix_ai_messages_user_id", "ai_messages", ["user_id"])
    op.create_index("ix_ai_messages_conversation_id", "ai_messages", ["conversation_id"])

    op.create_table(
        "ai_tool_calls",
        sa.Column("id", Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("message_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("provider_call_id", sa.String(length=100), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("input_sanitized", sa.JSON(), nullable=False),
        sa.Column("output_sanitized", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING_CONFIRMATION', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_ai_tool_calls_status",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_ai_tool_calls_duration"
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_tool_calls_input_tokens"
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_tool_calls_output_tokens"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "user_id"],
            ["ai_conversations.id", "ai_conversations.user_id"],
            ondelete="CASCADE",
            name="fk_ai_tool_calls_conversation_owner",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "user_id"],
            ["ai_messages.id", "ai_messages.user_id"],
            ondelete="CASCADE",
            name="fk_ai_tool_calls_message_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_tool_calls_user_id", "ai_tool_calls", ["user_id"])

    op.create_table(
        "ai_memories",
        sa.Column("id", Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("content", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind = 'PREFERENCE'", name="ck_ai_memories_kind"),
        sa.CheckConstraint(
            "length(content) BETWEEN 1 AND 500", name="ck_ai_memories_content_length"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_memories_user_id", "ai_memories", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_memories_user_id", table_name="ai_memories")
    op.drop_table("ai_memories")
    op.drop_index("ix_ai_tool_calls_user_id", table_name="ai_tool_calls")
    op.drop_table("ai_tool_calls")
    op.drop_index("ix_ai_messages_conversation_id", table_name="ai_messages")
    op.drop_index("ix_ai_messages_user_id", table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index("ix_ai_conversations_user_id", table_name="ai_conversations")
    op.drop_table("ai_conversations")

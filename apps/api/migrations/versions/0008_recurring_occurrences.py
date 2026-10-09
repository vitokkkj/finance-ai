"""Add recurring rules and materialized occurrences.

Revision ID: 0008_recurring_occurrences
Revises: 0007_ai_diagnostics
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_recurring_occurrences"
down_revision = "0007_ai_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_transactions_id_user_id", "transactions", ["id", "user_id"]
    )
    op.create_table(
        "recurrence_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("frequency", sa.String(length=10), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("type IN ('INCOME', 'EXPENSE')", name="ck_recurrence_rules_type"),
        sa.CheckConstraint("amount > 0", name="ck_recurrence_rules_amount_positive"),
        sa.CheckConstraint("currency = 'BRL'", name="ck_recurrence_rules_currency_brl"),
        sa.CheckConstraint(
            "frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY')",
            name="ck_recurrence_rules_frequency",
        ),
        sa.CheckConstraint("interval BETWEEN 1 AND 365", name="ck_recurrence_rules_interval"),
        sa.CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on", name="ck_recurrence_rules_date_order"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_recurrence_rules_account_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_recurrence_rules_category_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_recurrence_rules_id_user_id"),
    )
    op.create_index("ix_recurrence_rules_user_id", "recurrence_rules", ["user_id"])

    op.create_table(
        "recurrence_occurrences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("type IN ('INCOME', 'EXPENSE')", name="ck_recurrence_occurrences_type"),
        sa.CheckConstraint("amount > 0", name="ck_recurrence_occurrences_amount_positive"),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'PAID', 'SKIPPED', 'CANCELLED')",
            name="ck_recurrence_occurrences_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rule_id", "user_id"],
            ["recurrence_rules.id", "recurrence_rules.user_id"],
            name="fk_recurrence_occurrences_rule_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id", "user_id"],
            ["transactions.id", "transactions.user_id"],
            name="fk_recurrence_occurrences_transaction_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "user_id"],
            ["accounts.id", "accounts.user_id"],
            name="fk_recurrence_occurrences_account_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "user_id"],
            ["categories.id", "categories.user_id"],
            name="fk_recurrence_occurrences_category_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_recurrence_occurrences_id_user_id"),
        sa.UniqueConstraint(
            "rule_id", "user_id", "due_date", name="uq_recurrence_occurrence_rule_date"
        ),
        sa.UniqueConstraint("transaction_id", name="uq_recurrence_occurrence_transaction"),
    )
    op.create_index(
        "ix_recurrence_occurrences_user_id", "recurrence_occurrences", ["user_id"]
    )
    op.create_index(
        "ix_recurrence_occurrences_rule_id", "recurrence_occurrences", ["rule_id"]
    )
    op.create_index(
        "ix_recurrence_occurrences_due_date", "recurrence_occurrences", ["due_date"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_data = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM recurrence_rules) "
            "OR EXISTS (SELECT 1 FROM recurrence_occurrences)"
        )
    ).scalar_one()
    if has_data:
        raise RuntimeError("Não é seguro remover o schema de recorrências que já contém dados.")

    op.drop_index("ix_recurrence_occurrences_due_date", table_name="recurrence_occurrences")
    op.drop_index("ix_recurrence_occurrences_rule_id", table_name="recurrence_occurrences")
    op.drop_index("ix_recurrence_occurrences_user_id", table_name="recurrence_occurrences")
    op.drop_table("recurrence_occurrences")
    op.drop_index("ix_recurrence_rules_user_id", table_name="recurrence_rules")
    op.drop_table("recurrence_rules")
    op.drop_constraint("uq_transactions_id_user_id", "transactions", type_="unique")

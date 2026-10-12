import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    Account,
    CardInvoice,
    Category,
    CreditCard,
    PlannedCommitment,
    RecurrenceOccurrence,
    RecurrenceRule,
    Transaction,
    User,
)

router = APIRouter(tags=["exportação"])


def _iso_value(value: object) -> str | int | bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        instant = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return instant.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return value
    raise TypeError(f"Tipo não suportado no formato de exportação: {type(value).__name__}")


def _records[ExportRow](
    db: Session, statement: Select[ExportRow], fields: tuple[str, ...]
) -> list[dict[str, str | int | bool | None]]:
    rows = db.scalars(statement).all()
    return [
        {field: _iso_value(getattr(row, field)) for field in fields}
        for row in rows
    ]


@router.get("/api/export", response_class=Response)
def export_finances(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    exported_at = datetime.now(UTC)
    export_data = {
        "format": "sophia-finance-export",
        "schema_version": 1,
        "exported_at": _iso_value(exported_at),
        "data": {
            "accounts": _records(
                db,
                select(Account)
                .where(Account.user_id == user.id)
                .order_by(Account.name, Account.id),
                (
                    "id",
                    "name",
                    "type",
                    "currency",
                    "opening_balance",
                    "opening_balance_date",
                    "is_active",
                    "created_at",
                    "updated_at",
                ),
            ),
            "categories": _records(
                db,
                select(Category)
                .where(Category.user_id == user.id)
                .order_by(Category.name, Category.id),
                ("id", "name", "type", "archived_at", "created_at", "updated_at"),
            ),
            "transactions": _records(
                db,
                select(Transaction)
                .where(Transaction.user_id == user.id)
                .order_by(Transaction.occurred_at, Transaction.created_at, Transaction.id),
                (
                    "id",
                    "account_id",
                    "category_id",
                    "source_account_id",
                    "destination_account_id",
                    "card_invoice_id",
                    "type",
                    "source",
                    "status",
                    "description",
                    "amount",
                    "occurred_at",
                    "notes",
                    "created_at",
                    "updated_at",
                ),
            ),
            "credit_cards": _records(
                db,
                select(CreditCard)
                .where(CreditCard.user_id == user.id)
                .order_by(CreditCard.name, CreditCard.id),
                (
                    "id",
                    "name",
                    "institution",
                    "credit_limit",
                    "currency",
                    "closing_day",
                    "due_day",
                    "payment_account_id",
                    "is_active",
                    "created_at",
                    "updated_at",
                ),
            ),
            "card_invoices": _records(
                db,
                select(CardInvoice)
                .where(CardInvoice.user_id == user.id)
                .order_by(CardInvoice.due_date, CardInvoice.closing_date, CardInvoice.id),
                (
                    "id",
                    "credit_card_id",
                    "period_start",
                    "period_end",
                    "closing_date",
                    "due_date",
                    "opening_balance",
                    "created_at",
                ),
            ),
            "planned_commitments": _records(
                db,
                select(PlannedCommitment)
                .where(PlannedCommitment.user_id == user.id)
                .order_by(PlannedCommitment.due_date, PlannedCommitment.id),
                (
                    "id",
                    "transaction_id",
                    "account_id",
                    "category_id",
                    "type",
                    "description",
                    "amount",
                    "due_date",
                    "notes",
                    "status",
                    "created_at",
                    "updated_at",
                ),
            ),
            "recurrence_rules": _records(
                db,
                select(RecurrenceRule)
                .where(RecurrenceRule.user_id == user.id)
                .order_by(RecurrenceRule.starts_on, RecurrenceRule.id),
                (
                    "id",
                    "account_id",
                    "category_id",
                    "type",
                    "description",
                    "amount",
                    "currency",
                    "frequency",
                    "interval",
                    "starts_on",
                    "ends_on",
                    "notes",
                    "is_active",
                    "created_at",
                    "updated_at",
                ),
            ),
            "recurrence_occurrences": _records(
                db,
                select(RecurrenceOccurrence)
                .where(RecurrenceOccurrence.user_id == user.id)
                .order_by(RecurrenceOccurrence.due_date, RecurrenceOccurrence.id),
                (
                    "id",
                    "rule_id",
                    "transaction_id",
                    "account_id",
                    "category_id",
                    "type",
                    "description",
                    "amount",
                    "due_date",
                    "notes",
                    "status",
                    "created_at",
                    "updated_at",
                ),
            ),
        },
    }
    body = json.dumps(export_data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    filename = f"sophia-financas-{exported_at:%Y%m%d}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )

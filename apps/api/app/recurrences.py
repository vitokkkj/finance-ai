from calendar import monthrange
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.finance_engine import current_financial_date, financial_day_start
from app.models import Account, Category, RecurrenceOccurrence, RecurrenceRule, Transaction, User
from app.schemas import (
    RecurrenceCreate,
    RecurrenceOccurrenceResponse,
    RecurrenceOccurrenceUpdate,
    RecurrenceResponse,
    RecurrenceUpdate,
)

router = APIRouter(prefix="/api/recurrences", tags=["recorrências"])
OCCURRENCE_HORIZON_DAYS = 90
OCCURRENCE_STATUSES = ("PLANNED", "PAID", "SKIPPED", "CANCELLED")


def _add_months(anchor: date, offset: int) -> date:
    month_index = anchor.year * 12 + anchor.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(anchor.day, monthrange(year, month)[1])
    return date(year, month, day)


def _add_years(anchor: date, offset: int) -> date:
    year = anchor.year + offset
    day = min(anchor.day, monthrange(year, anchor.month)[1])
    return date(year, anchor.month, day)


def scheduled_dates(
    *, frequency: str, interval: int, starts_on: date, through: date, ends_on: date | None = None
) -> list[date]:
    """Return dates anchored to the original start date, without month-end drift."""
    if interval < 1:
        return []
    results: list[date] = []
    index = 0
    while index <= 10_000:
        offset = index * interval
        if frequency == "DAILY":
            due_date = starts_on + timedelta(days=offset)
        elif frequency == "WEEKLY":
            due_date = starts_on + timedelta(days=offset * 7)
        elif frequency == "MONTHLY":
            due_date = _add_months(starts_on, offset)
        elif frequency == "YEARLY":
            due_date = _add_years(starts_on, offset)
        else:
            return []
        if ends_on is not None and due_date > ends_on:
            break
        if due_date > through:
            break
        results.append(due_date)
        index += 1
    return results


def _validate_references(
    *,
    user_id: UUID,
    account_id: UUID,
    category_id: UUID,
    movement_type: str,
    reference_date: date,
    db: Session,
) -> tuple[Account, Category]:
    account = db.scalar(
        select(Account).where(
            Account.id == account_id,
            Account.user_id == user_id,
            Account.is_active.is_(True),
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada ou inativa.")
    if account.opening_balance_date is not None and reference_date < account.opening_balance_date:
        raise HTTPException(
            status_code=422,
            detail="A data prevista não pode anteceder o saldo inicial da conta.",
        )

    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user_id)
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    if category.archived_at is not None:
        raise HTTPException(status_code=409, detail="A categoria está arquivada.")
    if category.type != movement_type:
        raise HTTPException(
            status_code=422,
            detail="O tipo da categoria precisa corresponder ao tipo da recorrência.",
        )
    return account, category


def _rule_response(rule: RecurrenceRule) -> RecurrenceResponse:
    return RecurrenceResponse(
        id=rule.id,
        account_id=rule.account_id,
        category_id=rule.category_id,
        type=rule.type,
        description=rule.description,
        amount=rule.amount,
        currency=rule.currency,
        frequency=rule.frequency,
        interval=rule.interval,
        starts_on=rule.starts_on,
        ends_on=rule.ends_on,
        notes=rule.notes,
        is_active=rule.is_active,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _occurrence_response(occurrence: RecurrenceOccurrence) -> RecurrenceOccurrenceResponse:
    today = current_financial_date()
    if occurrence.status != "PLANNED":
        status_value = occurrence.status
    elif occurrence.due_date < today:
        status_value = "OVERDUE"
    elif occurrence.due_date == today:
        status_value = "PENDING"
    else:
        status_value = "PLANNED"
    return RecurrenceOccurrenceResponse(
        id=occurrence.id,
        rule_id=occurrence.rule_id,
        transaction_id=occurrence.transaction_id,
        account_id=occurrence.account_id,
        category_id=occurrence.category_id,
        type=occurrence.type,
        description=occurrence.description,
        amount=occurrence.amount,
        due_date=occurrence.due_date,
        notes=occurrence.notes,
        status=status_value,
    )


def _occurrence_from_rule(rule: RecurrenceRule, due_date: date) -> RecurrenceOccurrence:
    return RecurrenceOccurrence(
        user_id=rule.user_id,
        rule_id=rule.id,
        account_id=rule.account_id,
        category_id=rule.category_id,
        type=rule.type,
        description=rule.description,
        amount=rule.amount,
        due_date=due_date,
        notes=rule.notes,
        status="PLANNED",
    )


def _copy_rule_values(rule: RecurrenceRule, occurrence: RecurrenceOccurrence) -> None:
    occurrence.account_id = rule.account_id
    occurrence.category_id = rule.category_id
    occurrence.type = rule.type
    occurrence.description = rule.description
    occurrence.amount = rule.amount
    occurrence.notes = rule.notes


def ensure_occurrences(rule: RecurrenceRule, through: date, db: Session) -> int:
    if not rule.is_active:
        return 0
    existing_rows = db.scalars(
        select(RecurrenceOccurrence).where(
            RecurrenceOccurrence.rule_id == rule.id,
            RecurrenceOccurrence.user_id == rule.user_id,
        )
    ).all()
    existing_by_date = {occurrence.due_date: occurrence for occurrence in existing_rows}
    created = 0
    for due_date in scheduled_dates(
        frequency=rule.frequency,
        interval=rule.interval,
        starts_on=rule.starts_on,
        through=through,
        ends_on=rule.ends_on,
    ):
        occurrence = existing_by_date.get(due_date)
        if occurrence is None:
            db.add(_occurrence_from_rule(rule, due_date))
            created += 1
        elif occurrence.status == "CANCELLED" and occurrence.transaction_id is None:
            occurrence.status = "PLANNED"
            _copy_rule_values(rule, occurrence)
    db.flush()
    return created


def extend_active_occurrences(db: Session, today: date | None = None) -> int:
    local_today = today or current_financial_date()
    horizon = local_today + timedelta(days=OCCURRENCE_HORIZON_DAYS)
    rules = db.scalars(
        select(RecurrenceRule).where(RecurrenceRule.is_active.is_(True)).order_by(RecurrenceRule.id)
    ).all()
    created = sum(ensure_occurrences(rule, horizon, db) for rule in rules)
    db.commit()
    return created


def _owned_rule(rule_id: UUID, user_id: UUID, db: Session) -> RecurrenceRule:
    rule = db.scalar(
        select(RecurrenceRule).where(
            RecurrenceRule.id == rule_id,
            RecurrenceRule.user_id == user_id,
        )
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Recorrência não encontrada.")
    return rule


def _owned_occurrence(
    rule_id: UUID,
    occurrence_id: UUID,
    user_id: UUID,
    db: Session,
    *,
    for_update: bool = False,
) -> RecurrenceOccurrence:
    statement = select(RecurrenceOccurrence).where(
        RecurrenceOccurrence.id == occurrence_id,
        RecurrenceOccurrence.rule_id == rule_id,
        RecurrenceOccurrence.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    occurrence = db.scalar(statement)
    if occurrence is None:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada.")
    return occurrence


def _validate_rule_schedule(starts_on: date, ends_on: date | None) -> None:
    today = current_financial_date()
    if starts_on < today:
        raise HTTPException(
            status_code=422,
            detail="A primeira ocorrência deve começar hoje ou em uma data futura.",
        )
    if ends_on is not None and ends_on < starts_on:
        raise HTTPException(
            status_code=422, detail="O fim da recorrência deve ser posterior ao início."
        )


def validate_recurrence(
    payload: RecurrenceCreate, user: User, db: Session
) -> tuple[Account, Category]:
    """Validate a proposed rule without writing it, for both API and chat previews."""
    _validate_rule_schedule(payload.starts_on, payload.ends_on)
    account, category = _validate_references(
        user_id=user.id,
        account_id=payload.account_id,
        category_id=payload.category_id,
        movement_type=payload.type,
        reference_date=payload.starts_on,
        db=db,
    )
    candidates = db.scalars(
        select(RecurrenceRule).where(
            RecurrenceRule.user_id == user.id,
            RecurrenceRule.account_id == payload.account_id,
            RecurrenceRule.category_id == payload.category_id,
            RecurrenceRule.type == payload.type,
            RecurrenceRule.amount == payload.amount,
            RecurrenceRule.frequency == payload.frequency,
            RecurrenceRule.interval == payload.interval,
            RecurrenceRule.starts_on == payload.starts_on,
            RecurrenceRule.ends_on == payload.ends_on,
            RecurrenceRule.is_active.is_(True),
        )
    ).all()
    normalized_description = payload.description.strip().casefold()
    normalized_notes = (payload.notes or "").strip().casefold()
    if any(
        rule.description.strip().casefold() == normalized_description
        and (rule.notes or "").strip().casefold() == normalized_notes
        for rule in candidates
    ):
        raise HTTPException(
            status_code=409,
            detail="Já existe um compromisso igual para esta conta e período.",
        )
    return account, category


def create_recurrence_for_user(
    payload: RecurrenceCreate, user: User, db: Session
) -> RecurrenceResponse:
    validate_recurrence(payload, user, db)
    rule = RecurrenceRule(
        user_id=user.id,
        account_id=payload.account_id,
        category_id=payload.category_id,
        type=payload.type,
        description=payload.description,
        amount=payload.amount,
        frequency=payload.frequency,
        interval=payload.interval,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        notes=payload.notes,
    )
    db.add(rule)
    db.flush()
    ensure_occurrences(
        rule, current_financial_date() + timedelta(days=OCCURRENCE_HORIZON_DAYS), db
    )
    db.commit()
    db.refresh(rule)
    return _rule_response(rule)


@router.get("", response_model=list[RecurrenceResponse])
def list_recurrences(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_inactive: bool = False,
) -> list[RecurrenceResponse]:
    statement = select(RecurrenceRule).where(RecurrenceRule.user_id == user.id)
    if not include_inactive:
        statement = statement.where(RecurrenceRule.is_active.is_(True))
    rules = db.scalars(statement.order_by(RecurrenceRule.created_at.desc())).all()
    return [_rule_response(rule) for rule in rules]


@router.get("/occurrences", response_model=list[RecurrenceOccurrenceResponse])
def list_occurrences(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[RecurrenceOccurrenceResponse]:
    today = current_financial_date()
    start = start_date or today - timedelta(days=30)
    end = end_date or today + timedelta(days=OCCURRENCE_HORIZON_DAYS)
    if end < start or (end - start).days > 366:
        raise HTTPException(status_code=422, detail="O período deve ter até 366 dias.")
    occurrences = db.scalars(
        select(RecurrenceOccurrence)
        .where(
            RecurrenceOccurrence.user_id == user.id,
            RecurrenceOccurrence.due_date >= start,
            RecurrenceOccurrence.due_date <= end,
        )
        .order_by(RecurrenceOccurrence.due_date, RecurrenceOccurrence.created_at)
    ).all()
    return [_occurrence_response(occurrence) for occurrence in occurrences]


@router.post("", response_model=RecurrenceResponse, status_code=status.HTTP_201_CREATED)
def create_recurrence(
    payload: RecurrenceCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RecurrenceResponse:
    return create_recurrence_for_user(payload, user, db)


@router.patch("/{rule_id}", response_model=RecurrenceResponse)
def update_recurrence(
    rule_id: UUID,
    payload: RecurrenceUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RecurrenceResponse:
    rule = _owned_rule(rule_id, user.id, db)
    if not rule.is_active:
        raise HTTPException(status_code=409, detail="Reative a recorrência antes de alterá-la.")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Informe ao menos um campo para alterar.")
    non_nullable_fields = (
        "account_id",
        "category_id",
        "type",
        "description",
        "amount",
        "frequency",
        "interval",
        "starts_on",
    )
    for field in non_nullable_fields:
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail="Os campos informados não podem ser nulos.")

    today = current_financial_date()
    next_start = changes.get("starts_on", rule.starts_on)
    next_end = changes.get("ends_on", rule.ends_on)
    if "starts_on" in changes and next_start < today:
        raise HTTPException(
            status_code=422,
            detail="A nova primeira ocorrência deve ser hoje ou em uma data futura.",
        )
    if next_end is not None and next_end < next_start:
        raise HTTPException(
            status_code=422, detail="O fim da recorrência deve ser posterior ao início."
        )

    next_type = changes.get("type", rule.type)
    next_account_id = changes.get("account_id", rule.account_id)
    next_category_id = changes.get("category_id", rule.category_id)
    next_reference_date = max(next_start, today)
    _validate_references(
        user_id=user.id,
        account_id=next_account_id,
        category_id=next_category_id,
        movement_type=next_type,
        reference_date=next_reference_date,
        db=db,
    )

    schedule_fields = ("frequency", "interval", "starts_on", "ends_on")
    schedule_changed = any(field in changes for field in schedule_fields)
    for field, value in changes.items():
        setattr(rule, field, value)

    occurrences = db.scalars(
        select(RecurrenceOccurrence).where(
            RecurrenceOccurrence.rule_id == rule.id,
            RecurrenceOccurrence.user_id == user.id,
            RecurrenceOccurrence.status == "PLANNED",
        )
    ).all()
    if rule.ends_on is not None:
        for occurrence in occurrences:
            if occurrence.due_date > rule.ends_on:
                occurrence.status = "CANCELLED"
    if schedule_changed:
        for occurrence in occurrences:
            if occurrence.due_date >= today:
                occurrence.status = "CANCELLED"
    else:
        for occurrence in occurrences:
            if occurrence.due_date >= today:
                _copy_rule_values(rule, occurrence)

    if rule.ends_on is not None and rule.ends_on < today:
        rule.is_active = False
    else:
        ensure_occurrences(rule, today + timedelta(days=OCCURRENCE_HORIZON_DAYS), db)
    db.commit()
    db.refresh(rule)
    return _rule_response(rule)


@router.post("/{rule_id}/cancel", response_model=RecurrenceResponse)
def cancel_recurrence(
    rule_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RecurrenceResponse:
    rule = _owned_rule(rule_id, user.id, db)
    if rule.is_active:
        today = current_financial_date()
        future_occurrences = db.scalars(
            select(RecurrenceOccurrence).where(
                RecurrenceOccurrence.rule_id == rule.id,
                RecurrenceOccurrence.user_id == user.id,
                RecurrenceOccurrence.due_date > today,
                RecurrenceOccurrence.status == "PLANNED",
            )
        ).all()
        for occurrence in future_occurrences:
            occurrence.status = "CANCELLED"
        rule.is_active = False
        db.commit()
        db.refresh(rule)
    return _rule_response(rule)


@router.patch("/{rule_id}/occurrences/{occurrence_id}", response_model=RecurrenceOccurrenceResponse)
def update_occurrence(
    rule_id: UUID,
    occurrence_id: UUID,
    payload: RecurrenceOccurrenceUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RecurrenceOccurrenceResponse:
    rule = _owned_rule(rule_id, user.id, db)
    occurrence = _owned_occurrence(rule.id, occurrence_id, user.id, db, for_update=True)
    if occurrence.status != "PLANNED":
        raise HTTPException(status_code=409, detail="Esta ocorrência não pode mais ser alterada.")

    changes = payload.model_dump(exclude_unset=True, exclude={"scope"})
    if not changes:
        raise HTTPException(status_code=422, detail="Informe ao menos um campo para alterar.")
    for field in ("account_id", "category_id", "type", "description", "amount"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail="Os campos informados não podem ser nulos.")

    scope = payload.scope
    today = current_financial_date()
    targets: Sequence[RecurrenceOccurrence]
    if scope == "THIS":
        targets = [occurrence]
    else:
        statement = select(RecurrenceOccurrence).where(
            RecurrenceOccurrence.rule_id == rule.id,
            RecurrenceOccurrence.user_id == user.id,
            RecurrenceOccurrence.status == "PLANNED",
        )
        if scope == "THIS_AND_FUTURE":
            statement = statement.where(RecurrenceOccurrence.due_date >= occurrence.due_date)
        else:
            statement = statement.where(RecurrenceOccurrence.due_date >= today)
        targets = db.scalars(statement.order_by(RecurrenceOccurrence.due_date)).all()

    next_type = changes.get("type", occurrence.type)
    next_account_id = changes.get("account_id", occurrence.account_id)
    next_category_id = changes.get("category_id", occurrence.category_id)
    for target in targets:
        _validate_references(
            user_id=user.id,
            account_id=next_account_id,
            category_id=next_category_id,
            movement_type=next_type,
            reference_date=max(target.due_date, today),
            db=db,
        )

    if scope != "THIS":
        for field, value in changes.items():
            setattr(rule, field, value)
    for target in targets:
        for field, value in changes.items():
            setattr(target, field, value)
    db.commit()
    db.refresh(occurrence)
    return _occurrence_response(occurrence)


@router.post(
    "/{rule_id}/occurrences/{occurrence_id}/pay",
    response_model=RecurrenceOccurrenceResponse,
)
def pay_occurrence(
    rule_id: UUID,
    occurrence_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RecurrenceOccurrenceResponse:
    _owned_rule(rule_id, user.id, db)
    occurrence = _owned_occurrence(rule_id, occurrence_id, user.id, db, for_update=True)
    if occurrence.status == "PAID":
        return _occurrence_response(occurrence)
    if occurrence.status in ("SKIPPED", "CANCELLED"):
        raise HTTPException(
            status_code=409,
            detail="Esta ocorrência não pode ser registrada como paga.",
        )

    paid_on = current_financial_date()
    _validate_references(
        user_id=user.id,
        account_id=occurrence.account_id,
        category_id=occurrence.category_id,
        movement_type=occurrence.type,
        reference_date=paid_on,
        db=db,
    )
    transaction = Transaction(
        user_id=user.id,
        account_id=occurrence.account_id,
        category_id=occurrence.category_id,
        type=occurrence.type,
        source="MANUAL",
        status="CONFIRMED",
        description=occurrence.description,
        amount=occurrence.amount,
        occurred_at=financial_day_start(paid_on),
        notes=occurrence.notes,
    )
    db.add(transaction)
    db.flush()
    occurrence.transaction_id = transaction.id
    occurrence.status = "PAID"
    db.commit()
    db.refresh(occurrence)
    return _occurrence_response(occurrence)


@router.post(
    "/{rule_id}/occurrences/{occurrence_id}/skip",
    response_model=RecurrenceOccurrenceResponse,
)
def skip_occurrence(
    rule_id: UUID,
    occurrence_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RecurrenceOccurrenceResponse:
    _owned_rule(rule_id, user.id, db)
    occurrence = _owned_occurrence(rule_id, occurrence_id, user.id, db, for_update=True)
    if occurrence.status == "PAID":
        raise HTTPException(status_code=409, detail="Uma ocorrência paga não pode ser ignorada.")
    if occurrence.status == "PLANNED":
        occurrence.status = "SKIPPED"
        db.commit()
        db.refresh(occurrence)
    return _occurrence_response(occurrence)

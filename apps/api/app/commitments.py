from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.finance_engine import current_financial_date, financial_day_start
from app.models import Account, Category, PlannedCommitment, Transaction, User
from app.schemas import PlannedCommitmentCreate, PlannedCommitmentResponse, PlannedCommitmentUpdate

router = APIRouter(prefix="/api/commitments", tags=["compromissos previstos"])


def _owned(
    commitment_id: UUID, user_id: UUID, db: Session, *, for_update: bool = False
) -> PlannedCommitment:
    statement = select(PlannedCommitment).where(
        PlannedCommitment.id == commitment_id,
        PlannedCommitment.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    commitment = db.scalar(statement)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Compromisso não encontrado.")
    return commitment


def _validate_references(
    *,
    user_id: UUID,
    account_id: UUID,
    category_id: UUID,
    movement_type: str,
    due_date: date,
    db: Session,
) -> None:
    account = db.scalar(
        select(Account).where(
            Account.id == account_id, Account.user_id == user_id, Account.is_active.is_(True)
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada ou inativa.")
    if account.opening_balance_date is not None and due_date < account.opening_balance_date:
        raise HTTPException(
            status_code=422, detail="A data prevista não pode anteceder o saldo inicial da conta."
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
            status_code=422, detail="O tipo da categoria precisa corresponder ao compromisso."
        )


def _response(commitment: PlannedCommitment) -> PlannedCommitmentResponse:
    state = commitment.status
    if state == "PLANNED" and commitment.due_date < current_financial_date():
        state = "OVERDUE"
    return PlannedCommitmentResponse(
        id=commitment.id,
        transaction_id=commitment.transaction_id,
        account_id=commitment.account_id,
        category_id=commitment.category_id,
        type=commitment.type,
        description=commitment.description,
        amount=commitment.amount,
        due_date=commitment.due_date,
        notes=commitment.notes,
        status=state,
        created_at=commitment.created_at,
        updated_at=commitment.updated_at,
    )


@router.get("", response_model=list[PlannedCommitmentResponse])
def list_commitments(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_history: bool = False,
) -> list[PlannedCommitmentResponse]:
    statement = select(PlannedCommitment).where(PlannedCommitment.user_id == user.id)
    if not include_history:
        statement = statement.where(PlannedCommitment.status == "PLANNED")
    rows = db.scalars(
        statement.order_by(PlannedCommitment.due_date, PlannedCommitment.created_at)
    ).all()
    return [_response(row) for row in rows]


@router.post("", response_model=PlannedCommitmentResponse, status_code=status.HTTP_201_CREATED)
def create_commitment(
    payload: PlannedCommitmentCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PlannedCommitmentResponse:
    _validate_references(
        user_id=user.id,
        account_id=payload.account_id,
        category_id=payload.category_id,
        movement_type=payload.type,
        due_date=payload.due_date,
        db=db,
    )
    commitment = PlannedCommitment(
        user_id=user.id,
        account_id=payload.account_id,
        category_id=payload.category_id,
        type=payload.type,
        description=payload.description,
        amount=payload.amount,
        due_date=payload.due_date,
        notes=payload.notes,
        status="PLANNED",
    )
    db.add(commitment)
    db.commit()
    db.refresh(commitment)
    return _response(commitment)


@router.patch("/{commitment_id}", response_model=PlannedCommitmentResponse)
def update_commitment(
    commitment_id: UUID,
    payload: PlannedCommitmentUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PlannedCommitmentResponse:
    commitment = _owned(commitment_id, user.id, db, for_update=True)
    if commitment.status != "PLANNED":
        raise HTTPException(
            status_code=409, detail="Somente compromissos previstos podem ser editados."
        )
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Informe ao menos um campo para alterar.")
    for key in ("account_id", "category_id", "type", "description", "amount", "due_date"):
        if key in changes and changes[key] is None:
            raise HTTPException(status_code=422, detail="Os campos informados não podem ser nulos.")
    _validate_references(
        user_id=user.id,
        account_id=changes.get("account_id", commitment.account_id),
        category_id=changes.get("category_id", commitment.category_id),
        movement_type=changes.get("type", commitment.type),
        due_date=changes.get("due_date", commitment.due_date),
        db=db,
    )
    for key, value in changes.items():
        setattr(commitment, key, value)
    db.commit()
    db.refresh(commitment)
    return _response(commitment)


@router.post("/{commitment_id}/pay", response_model=PlannedCommitmentResponse)
def pay_commitment(
    commitment_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PlannedCommitmentResponse:
    commitment = _owned(commitment_id, user.id, db, for_update=True)
    if commitment.status == "PAID":
        return _response(commitment)
    if commitment.status == "CANCELLED":
        raise HTTPException(status_code=409, detail="Um compromisso cancelado não pode ser pago.")
    paid_on = current_financial_date()
    _validate_references(
        user_id=user.id,
        account_id=commitment.account_id,
        category_id=commitment.category_id,
        movement_type=commitment.type,
        due_date=paid_on,
        db=db,
    )
    transaction = Transaction(
        user_id=user.id,
        account_id=commitment.account_id,
        category_id=commitment.category_id,
        type=commitment.type,
        source="MANUAL",
        status="CONFIRMED",
        description=commitment.description,
        amount=commitment.amount,
        occurred_at=financial_day_start(paid_on),
        notes=commitment.notes,
    )
    db.add(transaction)
    db.flush()
    commitment.transaction_id = transaction.id
    commitment.status = "PAID"
    db.commit()
    db.refresh(commitment)
    return _response(commitment)


@router.post("/{commitment_id}/cancel", response_model=PlannedCommitmentResponse)
def cancel_commitment(
    commitment_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PlannedCommitmentResponse:
    commitment = _owned(commitment_id, user.id, db, for_update=True)
    if commitment.status == "PAID":
        raise HTTPException(status_code=409, detail="Um compromisso pago não pode ser cancelado.")
    if commitment.status == "PLANNED":
        commitment.status = "CANCELLED"
        db.commit()
        db.refresh(commitment)
    return _response(commitment)

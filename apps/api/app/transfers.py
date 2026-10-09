from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.finance_engine import current_financial_date, financial_day_start
from app.finance_views import transaction_response, transaction_rows
from app.models import Account, Transaction, User
from app.schemas import TransactionResponse, TransferCreate

router = APIRouter(tags=["transferências"])


@router.get("/api/transfers", response_model=list[TransactionResponse])
def list_transfers(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TransactionResponse]:
    rows = db.execute(
        transaction_rows(user.id)
        .where(Transaction.type == "TRANSFER")
        .order_by(Transaction.occurred_at.desc(), Transaction.created_at.desc())
    ).all()
    return [transaction_response(*row) for row in rows]


@router.post(
    "/api/transfers", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED
)
def create_transfer(
    payload: TransferCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TransactionResponse:
    if payload.source_account_id == payload.destination_account_id:
        raise HTTPException(
            status_code=422,
            detail="A conta de origem e a conta de destino precisam ser diferentes.",
        )
    if payload.occurred_at > current_financial_date():
        raise HTTPException(
            status_code=422, detail="A data da transferência não pode estar no futuro."
        )
    accounts = db.scalars(
        select(Account).where(
            Account.user_id == user.id,
            Account.id.in_([payload.source_account_id, payload.destination_account_id]),
            Account.is_active.is_(True),
        )
    ).all()
    accounts_by_id = {account.id: account for account in accounts}
    source = accounts_by_id.get(payload.source_account_id)
    destination = accounts_by_id.get(payload.destination_account_id)
    if source is None or destination is None:
        raise HTTPException(status_code=404, detail="Conta de origem ou destino não encontrada.")
    if (
        source.opening_balance_date is not None
        and payload.occurred_at < source.opening_balance_date
    ):
        raise HTTPException(
            status_code=422,
            detail="A data da transferência não pode anteceder o saldo inicial da conta de origem.",
        )
    if (
        destination.opening_balance_date is not None
        and payload.occurred_at < destination.opening_balance_date
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "A data da transferência não pode anteceder o saldo inicial da conta de destino."
            ),
        )

    transfer = Transaction(
        user_id=user.id,
        type="TRANSFER",
        source="MANUAL",
        status="CONFIRMED",
        source_account_id=source.id,
        destination_account_id=destination.id,
        description="Transferência entre contas próprias",
        amount=payload.amount,
        occurred_at=financial_day_start(payload.occurred_at),
        notes=payload.notes,
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transaction_response(transfer, None)

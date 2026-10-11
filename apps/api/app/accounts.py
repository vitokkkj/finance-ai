from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.finance_engine import (
    FinancialMovement,
    calculate_account_balance,
    current_financial_date,
    financial_date,
    financial_day_after,
)
from app.finance_views import movements_for_account
from app.models import Account, Transaction, User
from app.schemas import AccountCreate, AccountResponse, AccountUpdate

router = APIRouter(prefix="/api/accounts", tags=["contas"])


def _account_response(
    account: Account, movements: tuple[FinancialMovement, ...] = ()
) -> AccountResponse:
    today = current_financial_date()
    balance = None
    if account.opening_balance is not None and account.opening_balance_date is not None:
        balance = calculate_account_balance(
            opening_balance=account.opening_balance,
            opening_balance_date=account.opening_balance_date,
            movements=movements,
            as_of=today,
            account_id=account.id,
        )
    return AccountResponse(
        id=account.id,
        name=account.name,
        type=account.type,
        currency=account.currency,
        opening_balance=account.opening_balance,
        opening_balance_date=account.opening_balance_date,
        is_active=account.is_active,
        balance=balance,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


@router.get("", response_model=list[AccountResponse])
def list_accounts(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_archived: bool = False,
) -> list[AccountResponse]:
    statement = select(Account).where(Account.user_id == user.id)
    if not include_archived:
        statement = statement.where(Account.is_active.is_(True))
    accounts = db.scalars(statement.order_by(Account.created_at, Account.id)).all()
    if not accounts:
        return []
    account_ids = [account.id for account in accounts]
    transactions = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user.id,
            or_(
                Transaction.account_id.in_(account_ids),
                Transaction.source_account_id.in_(account_ids),
                Transaction.destination_account_id.in_(account_ids),
            ),
            Transaction.status == "CONFIRMED",
            Transaction.occurred_at < financial_day_after(current_financial_date()),
        )
    ).all()
    movements_by_account: dict[UUID, list[FinancialMovement]] = {
        account.id: [] for account in accounts
    }
    for account in accounts:
        relevant_transactions = [
            transaction
            for transaction in transactions
            if account.id
            in (
                transaction.account_id,
                transaction.source_account_id,
                transaction.destination_account_id,
            )
        ]
        movements_by_account[account.id] = movements_for_account(relevant_transactions)
    return [
        _account_response(account, tuple(movements_by_account[account.id])) for account in accounts
    ]


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AccountResponse:
    if (
        payload.opening_balance_date is not None
        and payload.opening_balance_date > current_financial_date()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data do saldo inicial não pode estar no futuro.",
        )
    account = Account(
        user_id=user.id,
        name=payload.name,
        type=payload.type,
        currency="BRL",
        opening_balance=payload.opening_balance,
        opening_balance_date=payload.opening_balance_date,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _account_response(account)


@router.patch("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AccountResponse:
    account = db.scalar(select(Account).where(Account.id == account_id, Account.user_id == user.id))
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada.")
    today = current_financial_date()
    if payload.opening_balance_date is not None and payload.opening_balance_date > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data do saldo inicial não pode estar no futuro.",
        )
    opening_fields = {"opening_balance", "opening_balance_date"}
    provided_opening_fields = opening_fields.intersection(payload.model_fields_set)
    new_opening_balance = (
        payload.opening_balance
        if "opening_balance" in payload.model_fields_set
        else account.opening_balance
    )
    new_opening_date = (
        payload.opening_balance_date
        if "opening_balance_date" in payload.model_fields_set
        else account.opening_balance_date
    )
    if (new_opening_balance is None) != (new_opening_date is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe o saldo inicial e sua data juntos, ou limpe os dois campos.",
        )
    if new_opening_date is not None and new_opening_date > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data do saldo inicial não pode estar no futuro.",
        )
    if new_opening_date != account.opening_balance_date and new_opening_date is not None:
        first_transaction = db.scalar(
            select(Transaction.occurred_at)
            .where(
                Transaction.user_id == user.id,
                or_(
                    Transaction.account_id == account.id,
                    Transaction.source_account_id == account.id,
                    Transaction.destination_account_id == account.id,
                ),
                Transaction.status == "CONFIRMED",
            )
            .order_by(Transaction.occurred_at)
            .limit(1)
        )
        if first_transaction is not None and financial_date(first_transaction) < new_opening_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A data do saldo inicial não pode ultrapassar lançamentos existentes.",
            )
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field not in opening_fields and value is not None:
            setattr(account, field, value)
    if provided_opening_fields:
        account.opening_balance = new_opening_balance
        account.opening_balance_date = new_opening_date
    db.commit()
    db.refresh(account)
    account_transactions = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user.id,
            or_(
                Transaction.account_id == account.id,
                Transaction.source_account_id == account.id,
                Transaction.destination_account_id == account.id,
            ),
            Transaction.status == "CONFIRMED",
        )
    ).all()
    movements = tuple(movements_for_account(account_transactions))
    return _account_response(account, movements)


@router.post("/{account_id}/archive", response_model=AccountResponse)
def archive_account(
    account_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AccountResponse:
    account = db.scalar(
        select(Account)
        .where(Account.id == account_id, Account.user_id == user.id)
        .with_for_update()
    )
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta não encontrada.")

    transactions = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user.id,
            or_(
                Transaction.account_id == account.id,
                Transaction.source_account_id == account.id,
                Transaction.destination_account_id == account.id,
            ),
            Transaction.status == "CONFIRMED",
            Transaction.occurred_at < financial_day_after(current_financial_date()),
        )
    ).all()
    movements = tuple(movements_for_account(transactions))
    account_response = _account_response(account, movements)
    if account_response.balance is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Informe o saldo inicial e a data-base antes de arquivar a conta.",
        )
    if account_response.balance != 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transfira ou concilie o saldo até R$ 0,00 antes de arquivar a conta.",
        )
    account.is_active = False
    db.commit()
    db.refresh(account)
    return _account_response(account, movements)

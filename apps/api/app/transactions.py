from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, TypedDict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.finance_engine import (
    FinancialMovement,
    calculate_account_balance,
    calculate_period_summary,
    current_financial_date,
    financial_date,
    financial_day_after,
    financial_day_start,
)
from app.finance_views import (
    card_invoice_response,
    credit_card_response,
    transaction_movement,
    transaction_response,
    transaction_rows,
)
from app.models import (
    Account,
    CardInvoice,
    Category,
    CreditCard,
    PlannedCommitment,
    RecurrenceOccurrence,
    Transaction,
    User,
)
from app.schemas import (
    AccountTypeBalanceSummary,
    CategoryExpenseSummary,
    DashboardSummary,
    ForecastItem,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)

router = APIRouter(tags=["lançamentos"])
ZERO = Decimal("0.00")
FinancialTransactionType = Literal["INCOME", "EXPENSE", "TRANSFER", "CARD_PURCHASE", "CARD_PAYMENT"]


class AccountTypeAggregate(TypedDict):
    count: int
    incomplete: int
    balance: Decimal


def _validate_references(
    user_id: UUID,
    account_id: UUID,
    category_id: UUID,
    transaction_type: str,
    occurred_on: date,
    db: Session,
) -> None:
    account = db.scalar(
        select(Account).where(
            Account.id == account_id,
            Account.user_id == user_id,
            Account.is_active.is_(True),
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Conta não encontrada.")

    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user_id)
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    if category.archived_at is not None:
        raise HTTPException(status_code=409, detail="A categoria está arquivada.")
    if category.type != transaction_type:
        raise HTTPException(
            status_code=422,
            detail="O tipo da categoria precisa corresponder ao tipo do lançamento.",
        )
    if account.opening_balance_date is not None and occurred_on < account.opening_balance_date:
        raise HTTPException(
            status_code=422,
            detail="A data do lançamento não pode anteceder o saldo inicial da conta.",
        )
    if occurred_on > current_financial_date():
        raise HTTPException(
            status_code=422, detail="A data do lançamento não pode estar no futuro."
        )


def _transaction_instant(occurred_on: date) -> datetime:
    return financial_day_start(occurred_on)


@router.get("/api/transactions", response_model=list[TransactionResponse])
def list_transactions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start_date: date | None = None,
    end_date: date | None = None,
    account_id: UUID | None = None,
    category_id: UUID | None = None,
    type: FinancialTransactionType | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[TransactionResponse]:
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(status_code=422, detail="O período informado é inválido.")
    statement = transaction_rows(user.id)
    if start_date is not None:
        statement = statement.where(Transaction.occurred_at >= financial_day_start(start_date))
    if end_date is not None:
        statement = statement.where(Transaction.occurred_at < financial_day_after(end_date))
    if account_id is not None:
        statement = statement.where(
            or_(
                Transaction.account_id == account_id,
                Transaction.source_account_id == account_id,
                Transaction.destination_account_id == account_id,
            )
        )
    if category_id is not None:
        statement = statement.where(Transaction.category_id == category_id)
    if type is not None:
        statement = statement.where(Transaction.type == type)
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Transaction.description.ilike(term),
                Transaction.notes.ilike(term),
                Category.name.ilike(term),
                CreditCard.name.ilike(term),
            )
        )
    rows = db.execute(
        statement.order_by(Transaction.occurred_at.desc(), Transaction.created_at.desc())
    ).all()
    return [transaction_response(*row) for row in rows]


@router.post(
    "/api/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED
)
def create_transaction(
    payload: TransactionCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TransactionResponse:
    _validate_references(
        user.id,
        payload.account_id,
        payload.category_id,
        payload.type,
        payload.occurred_at,
        db,
    )
    transaction = Transaction(
        user_id=user.id,
        account_id=payload.account_id,
        category_id=payload.category_id,
        type=payload.type,
        source="MANUAL",
        status="CONFIRMED",
        description=payload.description,
        amount=payload.amount,
        occurred_at=_transaction_instant(payload.occurred_at),
        notes=payload.notes,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    category_name = db.scalar(
        select(Category.name).where(
            Category.id == transaction.category_id, Category.user_id == user.id
        )
    )
    return transaction_response(transaction, category_name)


@router.patch("/api/transactions/{transaction_id}", response_model=TransactionResponse)
def update_transaction(
    transaction_id: UUID,
    payload: TransactionUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TransactionResponse:
    transaction = db.scalar(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado.")
    if transaction.type not in ("INCOME", "EXPENSE"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Este movimento usa uma operação própria e não pode ser alterado por este endpoint."
            ),
        )
    if (
        db.scalar(
            select(PlannedCommitment.id)
            .where(PlannedCommitment.transaction_id == transaction.id)
            .limit(1)
        )
        is not None
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "O lançamento está vinculado a um compromisso pago e não pode ser alterado "
                "por este endpoint."
            ),
        )

    changes = {
        field: value
        for field, value in payload.model_dump(exclude_unset=True).items()
        if value is not None or field == "notes"
    }
    assert transaction.account_id is not None and transaction.category_id is not None
    new_account_id = changes.get("account_id", transaction.account_id)
    new_category_id = changes.get("category_id", transaction.category_id)
    new_type = changes.get("type", transaction.type)
    new_date = changes.get("occurred_at", financial_date(transaction.occurred_at))
    _validate_references(user.id, new_account_id, new_category_id, new_type, new_date, db)

    for field, value in changes.items():
        if field == "occurred_at" and value is not None:
            transaction.occurred_at = _transaction_instant(value)
        elif value is not None or field == "notes":
            setattr(transaction, field, value)
    db.commit()
    db.refresh(transaction)
    category_name = db.scalar(
        select(Category.name).where(
            Category.id == transaction.category_id, Category.user_id == user.id
        )
    )
    return transaction_response(transaction, category_name)


@router.delete("/api/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    transaction = db.scalar(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado.")
    if transaction.type not in ("INCOME", "EXPENSE"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Este movimento usa uma operação própria e não pode ser excluído por este endpoint."
            ),
        )
    recurrence_occurrence_id = db.scalar(
        select(RecurrenceOccurrence.id)
        .where(RecurrenceOccurrence.transaction_id == transaction.id)
        .limit(1)
    )
    if recurrence_occurrence_id is not None:
        raise HTTPException(
            status_code=409,
            detail="O lançamento está vinculado a uma recorrência e não pode ser excluído.",
        )
    planned_commitment_id = db.scalar(
        select(PlannedCommitment.id)
        .where(PlannedCommitment.transaction_id == transaction.id)
        .limit(1)
    )
    if planned_commitment_id is not None:
        raise HTTPException(
            status_code=409,
            detail="O lançamento está vinculado a um compromisso pago e não pode ser excluído.",
        )
    db.delete(transaction)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    year: int | None = Query(default=None, ge=2000, le=2200),
    month: int | None = Query(default=None, ge=1, le=12),
) -> DashboardSummary:
    today = current_financial_date()
    selected_year = year or today.year
    selected_month = month or today.month
    try:
        period_start = date(selected_year, selected_month, 1)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="O mês informado é inválido.") from error
    next_month = (
        date(selected_year + 1, 1, 1)
        if selected_month == 12
        else date(selected_year, selected_month + 1, 1)
    )
    period_end = next_month - timedelta(days=1)

    month_rows = db.execute(
        transaction_rows(user.id)
        .where(
            Transaction.status == "CONFIRMED",
            Transaction.occurred_at >= financial_day_start(period_start),
            Transaction.occurred_at < financial_day_start(next_month),
        )
        .order_by(Transaction.occurred_at.desc(), Transaction.created_at.desc())
    ).all()
    month_movements = [
        transaction_movement(transaction, category_name)
        for transaction, category_name, _, _ in month_rows
    ]
    summary = calculate_period_summary(month_movements, period_start, period_end)
    category_summaries = [
        CategoryExpenseSummary(category_id=category_id, category_name=name, amount=amount)
        for (category_id, name), amount in sorted(
            summary.expenses_by_category.items(), key=lambda row: (-row[1], row[0][1].casefold())
        )
    ]

    accounts = db.scalars(
        select(Account).where(Account.user_id == user.id, Account.is_active.is_(True))
    ).all()
    known_accounts = [
        account
        for account in accounts
        if account.opening_balance is not None and account.opening_balance_date is not None
    ]
    accounts_with_known_balance = [
        (account, account.opening_balance, account.opening_balance_date)
        for account in known_accounts
        if account.opening_balance is not None and account.opening_balance_date is not None
    ]
    account_balance_by_id: dict[UUID, Decimal] = {}
    if accounts_with_known_balance:
        account_ids = [account.id for account, _, _ in accounts_with_known_balance]
        balance_transactions = db.scalars(
            select(Transaction).where(
                Transaction.user_id == user.id,
                or_(
                    Transaction.account_id.in_(account_ids),
                    Transaction.source_account_id.in_(account_ids),
                    Transaction.destination_account_id.in_(account_ids),
                ),
                Transaction.status == "CONFIRMED",
                Transaction.occurred_at < financial_day_after(today),
            )
        ).all()
        movements_by_account: dict[UUID, list[FinancialMovement]] = {
            account.id: [] for account, _, _ in accounts_with_known_balance
        }
        for transaction in balance_transactions:
            movement = transaction_movement(transaction)
            for account, _, _ in accounts_with_known_balance:
                if account.id in (
                    transaction.account_id,
                    transaction.source_account_id,
                    transaction.destination_account_id,
                ):
                    movements_by_account[account.id].append(movement)
        account_balance_by_id = {
            account.id: calculate_account_balance(
                opening_balance,
                opening_balance_date,
                movements_by_account[account.id],
                today,
                account_id=account.id,
            )
            for account, opening_balance, opening_balance_date in accounts_with_known_balance
        }

    account_type_groups: dict[str, AccountTypeAggregate] = {}
    for account in accounts:
        group = account_type_groups.setdefault(
            account.type, {"count": 0, "incomplete": 0, "balance": ZERO}
        )
        group["count"] += 1
        if account.id not in account_balance_by_id:
            group["incomplete"] += 1
        else:
            group["balance"] += account_balance_by_id[account.id]

    forecast_end = (
        period_end
        if (selected_year, selected_month) == (today.year, today.month)
        else (
            date(today.year + 1, 1, 1) - timedelta(days=1)
            if today.month == 12
            else date(today.year, today.month + 1, 1) - timedelta(days=1)
        )
    )
    account_by_id = {
        account.id: account
        for account in db.scalars(select(Account).where(Account.user_id == user.id)).all()
    }
    forecast_items: list[ForecastItem] = []
    forecast_accounts_by_id: dict[str, Account | None] = {}

    def add_forecast_item(
        *,
        item_id: str,
        source: str,
        description: str,
        movement_type: str,
        due_date: date,
        amount: Decimal,
        account: Account | None = None,
        card_name: str | None = None,
    ) -> None:
        due_status = (
            "OVERDUE"
            if due_date < today
            else "DUE_SOON"
            if due_date <= today + timedelta(days=6)
            else "PLANNED"
        )
        forecast_items.append(
            ForecastItem(
                id=item_id,
                source=source,
                description=description,
                type=movement_type,
                due_date=due_date,
                amount=amount,
                account_type=account.type if account is not None else None,
                account_name=account.name if account is not None else None,
                card_name=card_name,
                status=due_status,
            )
        )
        forecast_accounts_by_id[item_id] = account

    planned_occurrences = db.scalars(
        select(RecurrenceOccurrence).where(
            RecurrenceOccurrence.user_id == user.id,
            RecurrenceOccurrence.status == "PLANNED",
            RecurrenceOccurrence.due_date <= forecast_end,
        )
    ).all()
    for occurrence in planned_occurrences:
        add_forecast_item(
            item_id=f"recurrence:{occurrence.id}",
            source="RECURRENCE",
            description=occurrence.description,
            movement_type=occurrence.type,
            due_date=occurrence.due_date,
            amount=occurrence.amount,
            account=account_by_id.get(occurrence.account_id),
        )

    commitments = db.scalars(
        select(PlannedCommitment).where(
            PlannedCommitment.user_id == user.id,
            PlannedCommitment.status == "PLANNED",
            PlannedCommitment.due_date <= forecast_end,
        )
    ).all()
    for commitment in commitments:
        add_forecast_item(
            item_id=f"commitment:{commitment.id}",
            source="COMMITMENT",
            description=commitment.description,
            movement_type=commitment.type,
            due_date=commitment.due_date,
            amount=commitment.amount,
            account=account_by_id.get(commitment.account_id),
        )

    all_cards = db.scalars(select(CreditCard).where(CreditCard.user_id == user.id)).all()
    card_by_id = {card.id: card for card in all_cards}
    invoices = db.scalars(
        select(CardInvoice).where(
            CardInvoice.user_id == user.id, CardInvoice.due_date <= forecast_end
        )
    ).all()
    unassigned_invoice_total = ZERO
    for invoice in invoices:
        invoice_summary = card_invoice_response(db, invoice, today)
        if invoice_summary.outstanding <= ZERO:
            continue
        card = card_by_id.get(invoice.credit_card_id)
        if card is None:
            continue
        payment_account = (
            account_by_id.get(card.payment_account_id) if card.payment_account_id else None
        )
        if payment_account is None or not payment_account.is_active:
            payment_account = None
            unassigned_invoice_total += invoice_summary.outstanding
        add_forecast_item(
            item_id=f"invoice:{invoice.id}",
            source="CARD_INVOICE",
            description=f"Fatura {card.name}",
            movement_type="EXPENSE",
            due_date=invoice.due_date,
            amount=invoice_summary.outstanding,
            account=payment_account,
            card_name=card.name,
        )

    forecast_items.sort(key=lambda item: (item.due_date, item.description.casefold(), item.id))
    overdue_total = sum(
        (
            item.amount
            for item in forecast_items
            if item.type == "EXPENSE" and item.status == "OVERDUE"
        ),
        start=ZERO,
    )
    next_7_days_total = sum(
        (
            item.amount
            for item in forecast_items
            if item.type == "EXPENSE" and item.status == "DUE_SOON"
        ),
        start=ZERO,
    )
    rest_of_month_total = sum(
        (
            item.amount
            for item in forecast_items
            if item.type == "EXPENSE" and item.status == "PLANNED"
        ),
        start=ZERO,
    )
    forecast_income_total = sum(
        (item.amount for item in forecast_items if item.type == "INCOME"), start=ZERO
    )
    forecast_payables_total = overdue_total + next_7_days_total + rest_of_month_total
    account_type_deltas: dict[str, Decimal] = {
        account_type: ZERO for account_type in account_type_groups
    }
    for item in forecast_items:
        payment_account = forecast_accounts_by_id[item.id]
        if payment_account is not None and not payment_account.is_active:
            payment_account = None
        if payment_account is None or payment_account.type not in account_type_deltas:
            continue
        account_type_deltas[payment_account.type] += (
            item.amount if item.type == "INCOME" else -item.amount
        )

    account_type_balances: list[AccountTypeBalanceSummary] = []
    for account_type, group in account_type_groups.items():
        count = group["count"]
        incomplete = group["incomplete"]
        balance = group["balance"] if incomplete == 0 else None
        projected = balance + account_type_deltas[account_type] if balance is not None else None
        account_type_balances.append(
            AccountTypeBalanceSummary(
                account_type=account_type,
                balance=balance,
                projected_balance=projected,
                account_count=count,
                incomplete_account_count=incomplete,
            )
        )
    checking_group = account_type_groups.get("CHECKING")
    incomplete_checking_account_count = checking_group["incomplete"] if checking_group else 0
    checking_balance = None
    if checking_group is not None and incomplete_checking_account_count == 0:
        checking_balance = checking_group["balance"]

    cards = db.scalars(select(CreditCard).where(CreditCard.user_id == user.id)).all()
    card_summaries = [credit_card_response(db, card, today) for card in cards if card.is_active]

    recent_rows = db.execute(
        transaction_rows(user.id)
        .where(Transaction.occurred_at < financial_day_after(today))
        .order_by(Transaction.occurred_at.desc(), Transaction.created_at.desc())
        .limit(10)
    ).all()
    recent_transactions = [transaction_response(*row) for row in recent_rows]

    return DashboardSummary(
        as_of=today,
        period_start=period_start,
        period_end=period_end,
        checking_balance=checking_balance,
        incomplete_checking_account_count=incomplete_checking_account_count,
        account_type_balances=account_type_balances,
        monthly_income=summary.income,
        monthly_expenses=summary.expenses,
        monthly_result=summary.result,
        expenses_by_category=category_summaries,
        cards=card_summaries,
        recent_transactions=recent_transactions,
        forecast_start=today,
        forecast_end=forecast_end,
        forecast_payables_total=forecast_payables_total,
        forecast_overdue_total=overdue_total,
        forecast_next_7_days_total=next_7_days_total,
        forecast_rest_of_month_total=rest_of_month_total,
        forecast_income_total=forecast_income_total,
        forecast_unassigned_invoice_total=unassigned_invoice_total,
        forecast_items=forecast_items,
    )

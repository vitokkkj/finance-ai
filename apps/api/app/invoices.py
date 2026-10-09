from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.finance_engine import (
    billing_cycle_for_purchase,
    current_financial_date,
    financial_day_start,
)
from app.finance_views import (
    card_invoice_response,
    invoice_amounts,
    transaction_response,
    transaction_rows,
)
from app.models import Account, CardInvoice, Category, CreditCard, Transaction, User
from app.schemas import (
    CardInvoiceResponse,
    CardPaymentCreate,
    CardPurchaseCreate,
    TransactionResponse,
)

router = APIRouter(tags=["faturas e pagamentos"])


def _get_invoice(
    db: Session, user_id: UUID, invoice_id: UUID, *, lock: bool = False
) -> CardInvoice:
    statement = select(CardInvoice).where(
        CardInvoice.id == invoice_id,
        CardInvoice.user_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    invoice = db.scalar(statement)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    return invoice


@router.post(
    "/api/card-purchases",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_card_purchase(
    payload: CardPurchaseCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TransactionResponse:
    if payload.occurred_at > current_financial_date():
        raise HTTPException(status_code=422, detail="A data da compra não pode estar no futuro.")
    card = db.scalar(
        select(CreditCard)
        .where(
            CreditCard.id == payload.credit_card_id,
            CreditCard.user_id == user.id,
            CreditCard.is_active.is_(True),
        )
        .with_for_update()
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")
    category = db.scalar(
        select(Category).where(Category.id == payload.category_id, Category.user_id == user.id)
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    if category.archived_at is not None:
        raise HTTPException(status_code=409, detail="A categoria está arquivada.")
    if category.type != "EXPENSE":
        raise HTTPException(status_code=422, detail="Compra no cartão exige categoria de despesa.")

    cycle = billing_cycle_for_purchase(payload.occurred_at, card.closing_day, card.due_day)
    invoice = db.scalar(
        select(CardInvoice).where(
            CardInvoice.credit_card_id == card.id,
            CardInvoice.user_id == user.id,
            CardInvoice.closing_date == cycle.closing_date,
        )
    )
    if invoice is None:
        invoice = CardInvoice(
            user_id=user.id,
            credit_card_id=card.id,
            period_start=cycle.period_start,
            period_end=cycle.period_end,
            closing_date=cycle.closing_date,
            due_date=cycle.due_date,
        )
        db.add(invoice)
        db.flush()

    purchase = Transaction(
        user_id=user.id,
        type="CARD_PURCHASE",
        source="MANUAL",
        status="CONFIRMED",
        category_id=category.id,
        card_invoice_id=invoice.id,
        description=payload.description,
        amount=payload.amount,
        occurred_at=financial_day_start(payload.occurred_at),
        notes=payload.notes,
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return transaction_response(purchase, category.name, card.id, card.name)


@router.get("/api/invoices/{invoice_id}", response_model=CardInvoiceResponse)
def get_invoice(
    invoice_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CardInvoiceResponse:
    invoice = _get_invoice(db, user.id, invoice_id)
    return card_invoice_response(db, invoice)


@router.post(
    "/api/invoices/{invoice_id}/payments",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def pay_invoice(
    invoice_id: UUID,
    payload: CardPaymentCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TransactionResponse:
    if payload.occurred_at > current_financial_date():
        raise HTTPException(status_code=422, detail="A data do pagamento não pode estar no futuro.")
    invoice = _get_invoice(db, user.id, invoice_id, lock=True)
    account = db.scalar(
        select(Account).where(
            Account.id == payload.account_id,
            Account.user_id == user.id,
            Account.is_active.is_(True),
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Conta pagadora não encontrada.")
    if (
        account.opening_balance_date is not None
        and payload.occurred_at < account.opening_balance_date
    ):
        raise HTTPException(
            status_code=422,
            detail="A data do pagamento não pode anteceder o saldo inicial da conta.",
        )
    amounts = invoice_amounts(db, invoice)
    if payload.amount > amounts.outstanding:
        raise HTTPException(
            status_code=422,
            detail="O pagamento não pode ultrapassar o saldo em aberto da fatura.",
        )
    if amounts.outstanding == 0:
        raise HTTPException(status_code=409, detail="A fatura já está quitada.")

    payment = Transaction(
        user_id=user.id,
        type="CARD_PAYMENT",
        source="MANUAL",
        status="CONFIRMED",
        account_id=account.id,
        card_invoice_id=invoice.id,
        description="Pagamento da fatura",
        amount=payload.amount,
        occurred_at=financial_day_start(payload.occurred_at),
        notes=payload.notes,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    card = db.get(CreditCard, invoice.credit_card_id)
    assert card is not None
    return transaction_response(payment, None, card.id, card.name)


@router.get("/api/invoices/{invoice_id}/payments", response_model=list[TransactionResponse])
def list_invoice_payments(
    invoice_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TransactionResponse]:
    _get_invoice(db, user.id, invoice_id)
    rows = db.execute(
        transaction_rows(user.id)
        .where(
            Transaction.card_invoice_id == invoice_id,
            Transaction.type == "CARD_PAYMENT",
        )
        .order_by(Transaction.occurred_at, Transaction.created_at)
    ).all()
    return [transaction_response(*row) for row in rows]

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.finance_engine import (
    CardLimitSummary,
    FinancialMovement,
    InvoiceAmounts,
    MovementType,
    calculate_card_limit,
    calculate_invoice_amounts,
    current_financial_date,
    financial_date,
)
from app.models import CardInvoice, Category, CreditCard, Transaction
from app.schemas import CardInvoiceResponse, CreditCardResponse, TransactionResponse


def transaction_rows(user_id: UUID) -> Select[Transaction, str, UUID, str]:
    return (
        select(Transaction, Category.name, CreditCard.id, CreditCard.name)
        .outerjoin(
            Category,
            and_(Transaction.category_id == Category.id, Transaction.user_id == Category.user_id),
        )
        .outerjoin(
            CardInvoice,
            and_(
                Transaction.card_invoice_id == CardInvoice.id,
                Transaction.user_id == CardInvoice.user_id,
            ),
        )
        .outerjoin(
            CreditCard,
            and_(
                CardInvoice.credit_card_id == CreditCard.id,
                Transaction.user_id == CreditCard.user_id,
            ),
        )
        .where(Transaction.user_id == user_id)
    )


def transaction_movement(
    transaction: Transaction, category_name: str | None = None
) -> FinancialMovement:
    return FinancialMovement(
        occurred_on=financial_date(transaction.occurred_at),
        type=cast(MovementType, transaction.type),
        amount=transaction.amount,
        status=transaction.status,
        category_id=transaction.category_id,
        category_name=category_name,
        account_id=transaction.account_id,
        source_account_id=transaction.source_account_id,
        destination_account_id=transaction.destination_account_id,
        invoice_id=transaction.card_invoice_id,
    )


def transaction_response(
    transaction: Transaction,
    category_name: str | None,
    credit_card_id: UUID | None = None,
    credit_card_name: str | None = None,
) -> TransactionResponse:
    return TransactionResponse(
        id=transaction.id,
        account_id=transaction.account_id,
        category_id=transaction.category_id,
        category_name=category_name,
        source_account_id=transaction.source_account_id,
        destination_account_id=transaction.destination_account_id,
        invoice_id=transaction.card_invoice_id,
        credit_card_id=credit_card_id,
        credit_card_name=credit_card_name,
        type=cast(MovementType, transaction.type),
        source=transaction.source,
        status=transaction.status,
        description=transaction.description,
        amount=transaction.amount,
        occurred_at=financial_date(transaction.occurred_at),
        notes=transaction.notes,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )


def invoice_movements(db: Session, invoice: CardInvoice) -> list[FinancialMovement]:
    rows = db.execute(
        transaction_rows(invoice.user_id).where(Transaction.card_invoice_id == invoice.id)
    ).all()
    return [
        transaction_movement(transaction, category_name)
        for transaction, category_name, _, _ in rows
    ]


def invoice_amounts(db: Session, invoice: CardInvoice, as_of: date | None = None) -> InvoiceAmounts:
    return calculate_invoice_amounts(
        invoice_movements(db, invoice),
        invoice.id,
        invoice.closing_date,
        invoice.due_date,
        as_of or current_financial_date(),
        invoice.opening_balance,
    )


def card_limit_summary(
    db: Session, card: CreditCard, as_of: date | None = None
) -> CardLimitSummary:
    invoices = db.scalars(
        select(CardInvoice).where(
            CardInvoice.credit_card_id == card.id,
            CardInvoice.user_id == card.user_id,
        )
    ).all()
    invoice_values = [
        (
            invoice.due_date,
            calculate_invoice_amounts(
                invoice_movements(db, invoice),
                invoice.id,
                invoice.closing_date,
                invoice.due_date,
                as_of or current_financial_date(),
                invoice.opening_balance,
            ),
        )
        for invoice in invoices
    ]
    return calculate_card_limit(card.credit_limit, invoice_values)


def credit_card_response(
    db: Session, card: CreditCard, as_of: date | None = None
) -> CreditCardResponse:
    limit_summary = card_limit_summary(db, card, as_of)
    return CreditCardResponse(
        id=card.id,
        name=card.name,
        institution=card.institution,
        credit_limit=card.credit_limit,
        currency=card.currency,
        closing_day=card.closing_day,
        due_day=card.due_day,
        is_active=card.is_active,
        used_limit=limit_summary.used_limit,
        available_limit=limit_summary.available_limit,
        next_due_date=limit_summary.next_due_date,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def card_invoice_response(
    db: Session, invoice: CardInvoice, as_of: date | None = None
) -> CardInvoiceResponse:
    card = db.scalar(
        select(CreditCard).where(
            CreditCard.id == invoice.credit_card_id,
            CreditCard.user_id == invoice.user_id,
        )
    )
    if card is None:
        raise RuntimeError("A fatura referencia um cartão inexistente.")
    rows = db.execute(
        transaction_rows(invoice.user_id)
        .where(Transaction.card_invoice_id == invoice.id)
        .order_by(Transaction.occurred_at, Transaction.created_at)
    ).all()
    amounts = calculate_invoice_amounts(
        (transaction_movement(row[0], row[1]) for row in rows),
        invoice.id,
        invoice.closing_date,
        invoice.due_date,
        as_of or current_financial_date(),
        invoice.opening_balance,
    )
    return CardInvoiceResponse(
        id=invoice.id,
        credit_card_id=card.id,
        credit_card_name=card.name,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        closing_date=invoice.closing_date,
        due_date=invoice.due_date,
        opening_balance=invoice.opening_balance,
        total=amounts.total,
        paid_amount=amounts.paid_amount,
        outstanding=amounts.outstanding,
        status=amounts.status,
        purchases=[transaction_response(*row) for row in rows if row[0].type == "CARD_PURCHASE"],
        payments=[transaction_response(*row) for row in rows if row[0].type == "CARD_PAYMENT"],
    )


def movements_for_account(transactions: Iterable[Transaction]) -> list[FinancialMovement]:
    return [transaction_movement(transaction) for transaction in transactions]

from __future__ import annotations

from collections.abc import Iterable, Sequence
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
        installment_group_id=transaction.installment_group_id,
        installment_number=transaction.installment_number,
        installment_count=transaction.installment_count,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )


def invoice_movements(db: Session, invoice: CardInvoice) -> list[FinancialMovement]:
    rows_by_invoice = _invoice_transaction_rows(db, invoice.user_id, [invoice.id])
    return [
        transaction_movement(transaction, category_name)
        for transaction, category_name, _, _ in rows_by_invoice[invoice.id]
    ]


def _invoice_transaction_rows(
    db: Session, user_id: UUID, invoice_ids: Sequence[UUID]
) -> dict[UUID, list[tuple[Transaction, str | None, UUID | None, str | None]]]:
    rows_by_invoice: dict[
        UUID, list[tuple[Transaction, str | None, UUID | None, str | None]]
    ] = {invoice_id: [] for invoice_id in invoice_ids}
    if not invoice_ids:
        return rows_by_invoice

    rows = db.execute(
        transaction_rows(user_id)
        .where(Transaction.card_invoice_id.in_(invoice_ids))
        .order_by(Transaction.card_invoice_id, Transaction.occurred_at, Transaction.created_at)
    ).all()
    for row in rows:
        invoice_id = row[0].card_invoice_id
        if invoice_id is not None:
            rows_by_invoice[invoice_id].append(row)
    return rows_by_invoice


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
    rows_by_invoice = _invoice_transaction_rows(
        db, card.user_id, [invoice.id for invoice in invoices]
    )
    return _card_limit_summary_from_rows(card, invoices, rows_by_invoice, as_of)


def _card_limit_summary_from_rows(
    card: CreditCard,
    invoices: Sequence[CardInvoice],
    rows_by_invoice: dict[
        UUID, list[tuple[Transaction, str | None, UUID | None, str | None]]
    ],
    as_of: date | None,
) -> CardLimitSummary:
    as_of_date = as_of or current_financial_date()
    invoice_values = []
    for invoice in invoices:
        movements = (
            transaction_movement(transaction, category_name)
            for transaction, category_name, _, _ in rows_by_invoice[invoice.id]
        )
        amounts = calculate_invoice_amounts(
            movements,
            invoice.id,
            invoice.closing_date,
            invoice.due_date,
            as_of_date,
            invoice.opening_balance,
        )
        invoice_values.append((invoice.due_date, amounts))
    return calculate_card_limit(card.credit_limit, invoice_values)


def credit_card_response(
    db: Session, card: CreditCard, as_of: date | None = None
) -> CreditCardResponse:
    limit_summary = card_limit_summary(db, card, as_of)
    return _credit_card_response(card, limit_summary)


def credit_card_responses(
    db: Session, cards: Sequence[CreditCard], as_of: date | None = None
) -> list[CreditCardResponse]:
    if not cards:
        return []
    user_id = cards[0].user_id
    if any(card.user_id != user_id for card in cards):
        raise ValueError("Os cartões do lote precisam pertencer ao mesmo usuário.")

    invoices = db.scalars(
        select(CardInvoice).where(
            CardInvoice.user_id == user_id,
            CardInvoice.credit_card_id.in_([card.id for card in cards]),
        )
    ).all()
    rows_by_invoice = _invoice_transaction_rows(
        db, user_id, [invoice.id for invoice in invoices]
    )
    invoices_by_card: dict[UUID, list[CardInvoice]] = {card.id: [] for card in cards}
    for invoice in invoices:
        invoices_by_card[invoice.credit_card_id].append(invoice)

    return [
        _credit_card_response(
            card,
            _card_limit_summary_from_rows(
                card, invoices_by_card[card.id], rows_by_invoice, as_of
            ),
        )
        for card in cards
    ]


def _credit_card_response(
    card: CreditCard, limit_summary: CardLimitSummary
) -> CreditCardResponse:
    return CreditCardResponse(
        id=card.id,
        name=card.name,
        institution=card.institution,
        credit_limit=card.credit_limit,
        currency=card.currency,
        closing_day=card.closing_day,
        due_day=card.due_day,
        payment_account_id=card.payment_account_id,
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
    return card_invoice_responses(db, [invoice], as_of)[0]


def card_invoice_responses(
    db: Session, invoices: Sequence[CardInvoice], as_of: date | None = None
) -> list[CardInvoiceResponse]:
    if not invoices:
        return []
    user_id = invoices[0].user_id
    if any(invoice.user_id != user_id for invoice in invoices):
        raise ValueError("As faturas do lote precisam pertencer ao mesmo usuário.")

    card_ids = {invoice.credit_card_id for invoice in invoices}
    cards_by_id = {
        card.id: card
        for card in db.scalars(
            select(CreditCard).where(
                CreditCard.user_id == user_id,
                CreditCard.id.in_(card_ids),
            )
        ).all()
    }
    rows_by_invoice = _invoice_transaction_rows(
        db, user_id, [invoice.id for invoice in invoices]
    )
    as_of_date = as_of or current_financial_date()
    responses: list[CardInvoiceResponse] = []
    for invoice in invoices:
        card = cards_by_id.get(invoice.credit_card_id)
        if card is None:
            raise RuntimeError("A fatura referencia um cartão inexistente.")
        rows = rows_by_invoice[invoice.id]
        amounts = calculate_invoice_amounts(
            (transaction_movement(row[0], row[1]) for row in rows),
            invoice.id,
            invoice.closing_date,
            invoice.due_date,
            as_of_date,
            invoice.opening_balance,
        )
        responses.append(
            CardInvoiceResponse(
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
                purchases=[
                    transaction_response(*row)
                    for row in rows
                    if row[0].type == "CARD_PURCHASE"
                ],
                payments=[
                    transaction_response(*row)
                    for row in rows
                    if row[0].type == "CARD_PAYMENT"
                ],
            )
        )
    return responses


def movements_for_account(transactions: Iterable[Transaction]) -> list[FinancialMovement]:
    return [transaction_movement(transaction) for transaction in transactions]

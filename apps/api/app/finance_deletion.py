from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardInvoice, PlannedCommitment, RecurrenceOccurrence, Transaction


def delete_transaction_record(
    db: Session,
    transaction: Transaction,
    *,
    occurrence_status: str = "PLANNED",
    commitment_status: str = "PLANNED",
) -> None:
    """Delete one movement and keep linked plans in a consistent state."""
    occurrences = db.scalars(
        select(RecurrenceOccurrence).where(RecurrenceOccurrence.transaction_id == transaction.id)
    ).all()
    commitments = db.scalars(
        select(PlannedCommitment).where(PlannedCommitment.transaction_id == transaction.id)
    ).all()
    for occurrence in occurrences:
        occurrence.transaction_id = None
        occurrence.status = occurrence_status
    for commitment in commitments:
        commitment.transaction_id = None
        commitment.status = commitment_status
    db.flush()
    db.delete(transaction)


def delete_invoice_record(db: Session, invoice: CardInvoice) -> tuple[int, int]:
    """Delete an invoice and its purchases/payments, returning their counts."""
    transactions = db.scalars(
        select(Transaction).where(
            Transaction.user_id == invoice.user_id,
            Transaction.card_invoice_id == invoice.id,
        )
    ).all()
    purchases = 0
    payments = 0
    for transaction in transactions:
        if transaction.type == "CARD_PURCHASE":
            purchases += 1
        elif transaction.type == "CARD_PAYMENT":
            payments += 1
        delete_transaction_record(db, transaction)
    db.flush()
    db.delete(invoice)
    return purchases, payments

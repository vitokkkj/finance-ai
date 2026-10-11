from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.finance_views import card_invoice_response, credit_card_response
from app.models import Account, CardInvoice, CreditCard, User
from app.schemas import CardInvoiceResponse, CreditCardCreate, CreditCardResponse, CreditCardUpdate

router = APIRouter(prefix="/api/cards", tags=["cartões"])


def _validate_payment_account(user_id: UUID, account_id: UUID | None, db: Session) -> None:
    if account_id is None:
        return
    account = db.scalar(
        select(Account).where(
            Account.id == account_id, Account.user_id == user_id, Account.is_active.is_(True)
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Conta pagadora não encontrada ou inativa.")


@router.get("", response_model=list[CreditCardResponse])
def list_cards(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    include_archived: bool = False,
) -> list[CreditCardResponse]:
    statement = select(CreditCard).where(CreditCard.user_id == user.id)
    if not include_archived:
        statement = statement.where(CreditCard.is_active.is_(True))
    cards = db.scalars(statement.order_by(CreditCard.name, CreditCard.id)).all()
    return [credit_card_response(db, card) for card in cards]


@router.post("", response_model=CreditCardResponse, status_code=status.HTTP_201_CREATED)
def create_card(
    payload: CreditCardCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CreditCardResponse:
    _validate_payment_account(user.id, payload.payment_account_id, db)
    card = CreditCard(
        user_id=user.id,
        name=payload.name,
        institution=payload.institution,
        credit_limit=payload.credit_limit,
        currency="BRL",
        closing_day=payload.closing_day,
        due_day=payload.due_day,
        payment_account_id=payload.payment_account_id,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return credit_card_response(db, card)


@router.patch("/{card_id}", response_model=CreditCardResponse)
def update_card(
    card_id: UUID,
    payload: CreditCardUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CreditCardResponse:
    card = db.scalar(
        select(CreditCard).where(CreditCard.id == card_id, CreditCard.user_id == user.id)
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")
    if not card.is_active:
        raise HTTPException(status_code=409, detail="O cartão está arquivado.")
    changes = payload.model_dump(exclude_unset=True)
    if "payment_account_id" in changes:
        _validate_payment_account(user.id, changes["payment_account_id"], db)
    for field, value in changes.items():
        setattr(card, field, value)
    db.commit()
    db.refresh(card)
    return credit_card_response(db, card)


@router.post("/{card_id}/archive", response_model=CreditCardResponse)
def archive_card(
    card_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CreditCardResponse:
    card = db.scalar(
        select(CreditCard).where(CreditCard.id == card_id, CreditCard.user_id == user.id)
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")
    card.is_active = False
    db.commit()
    db.refresh(card)
    return credit_card_response(db, card)


@router.get("/{card_id}/invoices", response_model=list[CardInvoiceResponse])
def list_card_invoices(
    card_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[CardInvoiceResponse]:
    card = db.scalar(
        select(CreditCard).where(CreditCard.id == card_id, CreditCard.user_id == user.id)
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")
    invoices = db.scalars(
        select(CardInvoice)
        .where(CardInvoice.credit_card_id == card.id, CardInvoice.user_id == user.id)
        .order_by(CardInvoice.closing_date.desc())
    ).all()
    return [card_invoice_response(db, invoice) for invoice in invoices]

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.finance_deletion import delete_invoice_record
from app.finance_engine import (
    BillingCycle,
    billing_cycle_for_closing_month,
    billing_cycle_for_due_month,
    billing_cycle_for_purchase,
    current_financial_date,
    financial_date,
    financial_day_start,
)
from app.finance_views import (
    card_invoice_response,
    invoice_amounts,
    transaction_response,
    transaction_rows,
)
from app.idempotency import (
    find_idempotent_transaction,
    recover_concurrent_idempotency,
    store_idempotency,
)
from app.models import Account, CardInvoice, Category, CreditCard, Transaction, User
from app.schemas import (
    CardInvoiceOpeningBalanceSet,
    CardInvoiceResponse,
    CardPaymentCreate,
    CardPurchaseCreate,
    CardPurchaseInstallmentPreview,
    CardPurchaseInstallmentResponse,
    CardPurchasePlanCreate,
    CardPurchasePlanPreview,
    CardPurchasePlanResponse,
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


def validate_invoice_opening_balance(db: Session, invoice: CardInvoice, amount: Decimal) -> Decimal:
    amounts = invoice_amounts(db, invoice)
    purchase_total = amounts.total - invoice.opening_balance
    if amounts.paid_amount > purchase_total + amount:
        raise HTTPException(
            status_code=409,
            detail="O saldo inicial não pode ficar abaixo dos pagamentos já registrados.",
        )
    return purchase_total


def invoice_opening_balance_from_total(
    db: Session, invoice: CardInvoice, invoice_total: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    amounts = invoice_amounts(db, invoice)
    purchase_total = amounts.total - invoice.opening_balance
    opening_balance = invoice_total - purchase_total
    if opening_balance < 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "O total informado é menor que as compras já registradas nessa fatura. "
                "Confira o mês e o valor antes de importar."
            ),
        )
    if amounts.paid_amount > invoice_total:
        raise HTTPException(
            status_code=409,
            detail="O total informado é menor que os pagamentos já registrados nessa fatura.",
        )
    return purchase_total, opening_balance, amounts.paid_amount


def set_invoice_opening_balances(
    db: Session,
    user: User,
    card_id: UUID,
    payloads: list[CardInvoiceOpeningBalanceSet],
    *,
    amounts_are_invoice_totals: bool = False,
) -> tuple[CreditCard, list[CardInvoice]]:
    """Apply one or more pre-existing invoice balances without creating purchases."""
    card = db.scalar(
        select(CreditCard)
        .where(
            CreditCard.id == card_id,
            CreditCard.user_id == user.id,
            CreditCard.is_active.is_(True),
        )
        .with_for_update()
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão ativo não encontrado.")

    prepared: list[
        tuple[CardInvoiceOpeningBalanceSet, BillingCycle, CardInvoice | None, Decimal]
    ] = []
    for payload in sorted(payloads, key=lambda item: item.due_month):
        year, month = (int(part) for part in payload.due_month.split("-"))
        cycle = billing_cycle_for_due_month(year, month, card.closing_day, card.due_day)
        invoice = db.scalar(
            select(CardInvoice)
            .where(
                CardInvoice.credit_card_id == card.id,
                CardInvoice.user_id == user.id,
                CardInvoice.closing_date == cycle.closing_date,
            )
            .with_for_update()
        )
        opening_balance = payload.amount
        if invoice is not None:
            if amounts_are_invoice_totals:
                _, opening_balance, _ = invoice_opening_balance_from_total(
                    db, invoice, payload.amount
                )
            else:
                validate_invoice_opening_balance(db, invoice, opening_balance)
        prepared.append((payload, cycle, invoice, opening_balance))

    invoices: list[CardInvoice] = []
    for _, cycle, invoice, opening_balance in prepared:
        if invoice is None:
            invoice = CardInvoice(
                user_id=user.id,
                credit_card_id=card.id,
                period_start=cycle.period_start,
                period_end=cycle.period_end,
                closing_date=cycle.closing_date,
                due_date=cycle.due_date,
                opening_balance=opening_balance,
            )
            db.add(invoice)
        else:
            invoice.opening_balance = opening_balance
        invoices.append(invoice)

    db.flush()
    return card, invoices


@router.post(
    "/api/card-purchases",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_card_purchase(
    payload: CardPurchaseCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TransactionResponse:
    user_id = user.id
    existing, fingerprint = find_idempotent_transaction(
        db, user_id, "card_purchase", idempotency_key, payload
    )
    if existing is not None:
        category_name = db.scalar(
            select(Category.name).where(
                Category.id == existing.category_id, Category.user_id == user_id
            )
        )
        card = db.scalar(
            select(CreditCard).where(
                CreditCard.id == payload.credit_card_id, CreditCard.user_id == user_id
            )
        )
        return transaction_response(
            existing, category_name, card.id if card else None, card.name if card else None
        )
    if payload.occurred_at > current_financial_date():
        raise HTTPException(status_code=422, detail="A data da compra não pode estar no futuro.")
    card = db.scalar(
        select(CreditCard)
        .where(
            CreditCard.id == payload.credit_card_id,
            CreditCard.user_id == user_id,
            CreditCard.is_active.is_(True),
        )
        .with_for_update()
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")
    category = db.scalar(
        select(Category).where(Category.id == payload.category_id, Category.user_id == user_id)
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    if category.archived_at is not None:
        raise HTTPException(status_code=409, detail="A categoria está arquivada.")
    if category.type != "EXPENSE":
        raise HTTPException(status_code=422, detail="Compra no cartão exige categoria de despesa.")

    cycle = billing_cycle_for_purchase(payload.occurred_at, card.closing_day, card.due_day)
    invoice = db.scalar(
        select(CardInvoice)
        .where(
            CardInvoice.credit_card_id == card.id,
            CardInvoice.user_id == user_id,
            CardInvoice.closing_date == cycle.closing_date,
        )
        .with_for_update()
    )
    if invoice is None:
        invoice = CardInvoice(
            user_id=user_id,
            credit_card_id=card.id,
            period_start=cycle.period_start,
            period_end=cycle.period_end,
            closing_date=cycle.closing_date,
            due_date=cycle.due_date,
        )
        db.add(invoice)
        db.flush()

    purchase = Transaction(
        user_id=user_id,
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
    try:
        store_idempotency(db, purchase, "card_purchase", idempotency_key, fingerprint)
        db.commit()
    except IntegrityError:
        existing = recover_concurrent_idempotency(
            db, user_id, "card_purchase", idempotency_key, fingerprint
        )
        if existing is None:
            raise
        return transaction_response(existing, category.name, card.id, card.name)
    db.refresh(purchase)
    return transaction_response(purchase, category.name, card.id, card.name)


def _resolve_card_purchase_plan(
    payload: CardPurchasePlanCreate,
    user: User,
    db: Session,
    *,
    lock_card: bool = False,
) -> tuple[CreditCard, Category, list[BillingCycle], list[Decimal]]:
    if payload.occurred_at > current_financial_date():
        raise HTTPException(status_code=422, detail="A data da compra não pode estar no futuro.")

    card_statement = select(CreditCard).where(
        CreditCard.id == payload.credit_card_id,
        CreditCard.user_id == user.id,
        CreditCard.is_active.is_(True),
    )
    if lock_card:
        card_statement = card_statement.with_for_update()
    card = db.scalar(card_statement)
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão ativo não encontrado.")

    category = db.scalar(
        select(Category).where(
            Category.id == payload.category_id,
            Category.user_id == user.id,
        )
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    if category.archived_at is not None:
        raise HTTPException(status_code=409, detail="A categoria está arquivada.")
    if category.type != "EXPENSE":
        raise HTTPException(status_code=422, detail="Compra no cartão exige categoria de despesa.")

    total_cents = int(payload.total_amount * 100)
    base_cents, extra_cents = divmod(total_cents, payload.installment_count)
    amounts = [
        Decimal(base_cents + (1 if index < extra_cents else 0)).scaleb(-2)
        for index in range(payload.installment_count)
    ]

    first_cycle = billing_cycle_for_purchase(
        payload.occurred_at, card.closing_day, card.due_day
    )
    cycles = [first_cycle]
    year, month = first_cycle.closing_date.year, first_cycle.closing_date.month
    for _ in range(1, payload.installment_count):
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
        cycles.append(
            billing_cycle_for_closing_month(year, month, card.closing_day, card.due_day)
        )
    return card, category, cycles, amounts


def preview_card_purchase_plan(
    payload: CardPurchasePlanCreate,
    user: User,
    db: Session,
) -> CardPurchasePlanPreview:
    """Validate and calculate installments without persisting invoices or transactions."""
    card, category, cycles, amounts = _resolve_card_purchase_plan(payload, user, db)
    return CardPurchasePlanPreview(
        credit_card_id=card.id,
        credit_card_name=card.name,
        category_id=category.id,
        category_name=category.name,
        description=payload.description,
        occurred_at=payload.occurred_at,
        total_amount=payload.total_amount,
        installment_count=payload.installment_count,
        installments=[
            CardPurchaseInstallmentPreview(
                number=index,
                amount=amount,
                closing_date=cycle.closing_date,
                due_date=cycle.due_date,
            )
            for index, (amount, cycle) in enumerate(zip(amounts, cycles, strict=True), start=1)
        ],
    )


def _card_purchase_plan_response(
    db: Session,
    user_id: UUID,
    group_id: UUID,
) -> CardPurchasePlanResponse:
    rows = db.execute(
        select(
            Transaction,
            CardInvoice.closing_date,
            CardInvoice.due_date,
            Category.name,
            CreditCard.id,
            CreditCard.name,
        )
        .join(
            CardInvoice,
            and_(
                Transaction.card_invoice_id == CardInvoice.id,
                Transaction.user_id == CardInvoice.user_id,
            ),
        )
        .join(
            Category,
            and_(
                Transaction.category_id == Category.id,
                Transaction.user_id == Category.user_id,
            ),
        )
        .join(
            CreditCard,
            and_(
                CardInvoice.credit_card_id == CreditCard.id,
                CardInvoice.user_id == CreditCard.user_id,
            ),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.installment_group_id == group_id,
            Transaction.type == "CARD_PURCHASE",
        )
        .order_by(Transaction.installment_number)
    ).all()
    if not rows:
        raise HTTPException(status_code=410, detail="As parcelas desta compra foram removidas.")

    first = rows[0]
    planned_count = first[0].installment_count
    if planned_count is None or len(rows) != planned_count or any(
        row[0].installment_number != index for index, row in enumerate(rows, start=1)
    ):
        raise HTTPException(
            status_code=410,
            detail=(
                "Uma ou mais parcelas desta compra foram removidas; "
                "a operação não pode ser repetida."
            ),
        )

    total_amount = sum((row[0].amount for row in rows), Decimal("0.00"))
    return CardPurchasePlanResponse(
        id=group_id,
        credit_card_id=first[4],
        credit_card_name=first[5],
        category_id=first[0].category_id,
        category_name=first[3],
        description=first[0].description,
        occurred_at=financial_date(first[0].occurred_at),
        notes=first[0].notes,
        total_amount=total_amount,
        installment_count=planned_count,
        installments=[
            CardPurchaseInstallmentResponse(
                number=row[0].installment_number,
                amount=row[0].amount,
                closing_date=row[1],
                due_date=row[2],
                transaction_id=row[0].id,
                invoice_id=row[0].card_invoice_id,
            )
            for row in rows
        ],
    )


def create_card_purchase_plan(
    payload: CardPurchasePlanCreate,
    user: User,
    db: Session,
    *,
    idempotency_key: str | None = None,
) -> CardPurchasePlanResponse:
    """Create installment transactions, each assigned to its own monthly card invoice."""
    user_id = user.id
    existing, fingerprint = find_idempotent_transaction(
        db, user_id, "card_purchase_plan", idempotency_key, payload
    )
    if existing is not None:
        if existing.installment_group_id is None:
            raise HTTPException(
                status_code=410,
                detail=(
                    "Esta operação já foi registrada, mas as parcelas originais foram removidas."
                ),
            )
        return _card_purchase_plan_response(db, user_id, existing.installment_group_id)

    card, category, cycles, amounts = _resolve_card_purchase_plan(
        payload, user, db, lock_card=True
    )
    group_id = uuid4()
    invoices_by_closing_date: dict[date, CardInvoice] = {}
    for cycle in cycles:
        invoice = db.scalar(
            select(CardInvoice)
            .where(
                CardInvoice.credit_card_id == card.id,
                CardInvoice.user_id == user_id,
                CardInvoice.closing_date == cycle.closing_date,
            )
            .with_for_update()
        )
        if invoice is None:
            invoice = CardInvoice(
                user_id=user_id,
                credit_card_id=card.id,
                period_start=cycle.period_start,
                period_end=cycle.period_end,
                closing_date=cycle.closing_date,
                due_date=cycle.due_date,
            )
            db.add(invoice)
            db.flush()
        invoices_by_closing_date[cycle.closing_date] = invoice

    purchases: list[Transaction] = []
    occurred_at = financial_day_start(payload.occurred_at)
    for index, (amount, cycle) in enumerate(zip(amounts, cycles, strict=True), start=1):
        purchase = Transaction(
            user_id=user_id,
            type="CARD_PURCHASE",
            source="MANUAL",
            status="CONFIRMED",
            category_id=category.id,
            card_invoice_id=invoices_by_closing_date[cycle.closing_date].id,
            installment_group_id=group_id,
            installment_number=index,
            installment_count=payload.installment_count,
            description=payload.description,
            amount=amount,
            occurred_at=occurred_at,
            notes=payload.notes,
        )
        db.add(purchase)
        purchases.append(purchase)

    try:
        store_idempotency(db, purchases[0], "card_purchase_plan", idempotency_key, fingerprint)
        db.commit()
    except IntegrityError:
        existing = recover_concurrent_idempotency(
            db, user_id, "card_purchase_plan", idempotency_key, fingerprint
        )
        if existing is None:
            raise
        if existing.installment_group_id is None:
            raise HTTPException(
                status_code=410,
                detail=(
                    "Esta operação já foi registrada, mas as parcelas originais foram removidas."
                ),
            ) from None
        return _card_purchase_plan_response(db, user_id, existing.installment_group_id)

    return _card_purchase_plan_response(db, user_id, group_id)


@router.post(
    "/api/card-purchase-plans",
    response_model=CardPurchasePlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_card_purchase_plan_route(
    payload: CardPurchasePlanCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CardPurchasePlanResponse:
    return create_card_purchase_plan(payload, user, db, idempotency_key=idempotency_key)


@router.put(
    "/api/cards/{card_id}/invoices/opening-balance",
    response_model=CardInvoiceResponse,
)
def set_invoice_opening_balance(
    card_id: UUID,
    payload: CardInvoiceOpeningBalanceSet,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CardInvoiceResponse:
    _, invoices = set_invoice_opening_balances(db, user, card_id, [payload])
    invoice = invoices[0]
    db.commit()
    db.refresh(invoice)
    return card_invoice_response(db, invoice)


@router.put("/api/invoices/{invoice_id}/opening-balance", response_model=CardInvoiceResponse)
def update_invoice_opening_balance(
    invoice_id: UUID,
    payload: CardInvoiceOpeningBalanceSet,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CardInvoiceResponse:
    invoice = _get_invoice(db, user.id, invoice_id)
    card = db.scalar(
        select(CreditCard)
        .where(CreditCard.id == invoice.credit_card_id, CreditCard.user_id == user.id)
        .with_for_update()
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")
    invoice = _get_invoice(db, user.id, invoice_id, lock=True)
    if invoice.opening_balance <= Decimal("0.00"):
        raise HTTPException(
            status_code=409,
            detail="Somente faturas com saldo inicial podem ter o ciclo ajustado.",
        )
    linked_transaction = db.scalar(
        select(Transaction.id)
        .where(Transaction.user_id == user.id, Transaction.card_invoice_id == invoice.id)
        .limit(1)
    )
    if linked_transaction is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta fatura tem compras ou pagamentos vinculados. Ajuste os registros "
                "associados para preservar a competência financeira."
            ),
        )

    year, month = (int(part) for part in payload.due_month.split("-"))
    cycle = billing_cycle_for_due_month(year, month, card.closing_day, card.due_day)
    other_invoice = db.scalar(
        select(CardInvoice.id).where(
            CardInvoice.credit_card_id == card.id,
            CardInvoice.user_id == user.id,
            CardInvoice.closing_date == cycle.closing_date,
            CardInvoice.id != invoice.id,
        )
    )
    if other_invoice is not None:
        raise HTTPException(
            status_code=409,
            detail="Já existe uma fatura neste ciclo. Nenhum saldo foi movido.",
        )

    invoice.period_start = cycle.period_start
    invoice.period_end = cycle.period_end
    invoice.closing_date = cycle.closing_date
    invoice.due_date = cycle.due_date
    invoice.opening_balance = payload.amount
    db.commit()
    db.refresh(invoice)
    return card_invoice_response(db, invoice)


@router.get("/api/invoices/{invoice_id}", response_model=CardInvoiceResponse)
def get_invoice(
    invoice_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CardInvoiceResponse:
    invoice = _get_invoice(db, user.id, invoice_id)
    return card_invoice_response(db, invoice)


@router.delete("/api/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    invoice = _get_invoice(db, user.id, invoice_id, lock=True)
    delete_invoice_record(db, invoice)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TransactionResponse:
    user_id = user.id
    idempotency_payload: dict[str, object] = {
        "invoice_id": str(invoice_id),
        "payment": payload.model_dump(mode="json"),
    }
    existing, fingerprint = find_idempotent_transaction(
        db, user_id, "invoice_payment", idempotency_key, idempotency_payload
    )
    if existing is not None:
        invoice = _get_invoice(db, user_id, existing.card_invoice_id or invoice_id)
        card = db.get(CreditCard, invoice.credit_card_id)
        assert card is not None
        return transaction_response(existing, None, card.id, card.name)
    invoice = _get_invoice(db, user_id, invoice_id, lock=True)
    existing, fingerprint = find_idempotent_transaction(
        db, user_id, "invoice_payment", idempotency_key, idempotency_payload
    )
    if existing is not None:
        card = db.get(CreditCard, invoice.credit_card_id)
        assert card is not None
        return transaction_response(existing, None, card.id, card.name)
    if payload.occurred_at > current_financial_date():
        raise HTTPException(status_code=422, detail="A data do pagamento não pode estar no futuro.")
    account = db.scalar(
        select(Account).where(
            Account.id == payload.account_id,
            Account.user_id == user_id,
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
        user_id=user_id,
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
    try:
        store_idempotency(db, payment, "invoice_payment", idempotency_key, fingerprint)
        db.commit()
    except IntegrityError:
        existing = recover_concurrent_idempotency(
            db, user_id, "invoice_payment", idempotency_key, fingerprint
        )
        if existing is None:
            raise
        invoice = _get_invoice(db, user_id, existing.card_invoice_id or invoice_id)
        card = db.get(CreditCard, invoice.credit_card_id)
        assert card is not None
        return transaction_response(existing, None, card.id, card.name)
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

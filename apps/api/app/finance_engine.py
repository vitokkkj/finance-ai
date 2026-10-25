from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

MovementType = Literal["INCOME", "EXPENSE", "TRANSFER", "CARD_PURCHASE", "CARD_PAYMENT"]
InvoiceStatus = Literal["OPEN", "CLOSED", "PARTIALLY_PAID", "PAID", "OVERDUE"]
FINANCIAL_TIME_ZONE = ZoneInfo("America/Sao_Paulo")
ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class FinancialMovement:
    occurred_on: date
    type: MovementType
    amount: Decimal
    status: str = "CONFIRMED"
    category_id: UUID | None = None
    category_name: str | None = None
    account_id: UUID | None = None
    source_account_id: UUID | None = None
    destination_account_id: UUID | None = None
    invoice_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    income: Decimal = ZERO
    expenses: Decimal = ZERO
    expenses_by_category: dict[tuple[UUID, str], Decimal] = field(default_factory=dict)

    @property
    def result(self) -> Decimal:
        return self.income - self.expenses


@dataclass(frozen=True, slots=True)
class TransactionFilterTotals:
    transaction_count: int = 0
    income_total: Decimal = ZERO
    expense_total: Decimal = ZERO
    card_purchase_total: Decimal = ZERO
    transfer_total: Decimal = ZERO
    card_payment_total: Decimal = ZERO

    @property
    def expenses_total(self) -> Decimal:
        return self.expense_total + self.card_purchase_total

    @property
    def result_total(self) -> Decimal:
        return self.income_total - self.expenses_total


def calculate_transaction_filter_totals(
    grouped_totals: Iterable[tuple[str, int, Decimal]],
) -> TransactionFilterTotals:
    """Classify exact database sums without counting transfers or invoice payments as expenses."""
    totals = {
        "INCOME": ZERO,
        "EXPENSE": ZERO,
        "CARD_PURCHASE": ZERO,
        "TRANSFER": ZERO,
        "CARD_PAYMENT": ZERO,
    }
    transaction_count = 0
    for movement_type, count, amount in grouped_totals:
        transaction_count += count
        if movement_type in totals:
            totals[movement_type] = amount
    return TransactionFilterTotals(
        transaction_count=transaction_count,
        income_total=totals["INCOME"],
        expense_total=totals["EXPENSE"],
        card_purchase_total=totals["CARD_PURCHASE"],
        transfer_total=totals["TRANSFER"],
        card_payment_total=totals["CARD_PAYMENT"],
    )


@dataclass(frozen=True, slots=True)
class InvoiceAmounts:
    total: Decimal
    paid_amount: Decimal
    outstanding: Decimal
    status: InvoiceStatus


@dataclass(frozen=True, slots=True)
class CardLimitSummary:
    used_limit: Decimal
    available_limit: Decimal
    next_due_date: date | None


@dataclass(frozen=True, slots=True)
class BillingCycle:
    period_start: date
    period_end: date
    closing_date: date
    due_date: date


def current_financial_date() -> date:
    return datetime.now(UTC).astimezone(FINANCIAL_TIME_ZONE).date()


def financial_day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, FINANCIAL_TIME_ZONE).astimezone(UTC)


def financial_day_after(day: date) -> datetime:
    return financial_day_start(day + timedelta(days=1))


def financial_date(instant: datetime) -> date:
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(FINANCIAL_TIME_ZONE).date()


def _month_date(year: int, month: int, day: int) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(day, last_day))


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def billing_cycle_for_purchase(purchase_date: date, closing_day: int, due_day: int) -> BillingCycle:
    """The close day is inclusive; a purchase after it goes to next month's invoice."""
    closing_date = _month_date(purchase_date.year, purchase_date.month, closing_day)
    if purchase_date > closing_date:
        year, month = _next_month(purchase_date.year, purchase_date.month)
        closing_date = _month_date(year, month, closing_day)

    previous_year, previous_month = _previous_month(closing_date.year, closing_date.month)
    previous_close = _month_date(previous_year, previous_month, closing_day)
    due_date = _month_date(closing_date.year, closing_date.month, due_day)
    if due_date <= closing_date:
        due_year, due_month = _next_month(closing_date.year, closing_date.month)
        due_date = _month_date(due_year, due_month, due_day)
    return BillingCycle(
        period_start=previous_close + timedelta(days=1),
        period_end=closing_date,
        closing_date=closing_date,
        due_date=due_date,
    )


def billing_cycle_for_closing_month(
    year: int, month: int, closing_day: int, due_day: int
) -> BillingCycle:
    """Return the scheduled invoice cycle for a month in which the card closes."""
    closing_date = _month_date(year, month, closing_day)
    return billing_cycle_for_purchase(closing_date, closing_day, due_day)


def billing_cycle_for_due_month(
    year: int, month: int, closing_day: int, due_day: int
) -> BillingCycle:
    """Return the scheduled invoice cycle for a month in which the invoice is due."""
    due_date_in_month = _month_date(year, month, due_day)
    closing_date_in_month = _month_date(year, month, closing_day)
    if due_date_in_month > closing_date_in_month:
        closing_year, closing_month = year, month
    else:
        closing_year, closing_month = _previous_month(year, month)
    return billing_cycle_for_closing_month(
        closing_year, closing_month, closing_day, due_day
    )


def calculate_account_balance(
    opening_balance: Decimal,
    opening_balance_date: date,
    movements: Iterable[FinancialMovement],
    as_of: date,
    account_id: UUID,
) -> Decimal:
    balance = opening_balance
    for movement in movements:
        if movement.status != "CONFIRMED":
            continue
        if not opening_balance_date <= movement.occurred_on <= as_of:
            continue
        if movement.type == "INCOME" and movement.account_id == account_id:
            balance += movement.amount
        elif movement.type == "EXPENSE" and movement.account_id == account_id:
            balance -= movement.amount
        elif movement.type == "TRANSFER":
            if movement.source_account_id == account_id:
                balance -= movement.amount
            if movement.destination_account_id == account_id:
                balance += movement.amount
        elif movement.type == "CARD_PAYMENT" and movement.account_id == account_id:
            balance -= movement.amount
    return balance


def calculate_period_summary(
    movements: Iterable[FinancialMovement], period_start: date, period_end: date
) -> PeriodSummary:
    income = ZERO
    expenses = ZERO
    category_expenses: dict[tuple[UUID, str], Decimal] = {}

    for movement in movements:
        if movement.status != "CONFIRMED":
            continue
        if not period_start <= movement.occurred_on <= period_end:
            continue
        if movement.type == "INCOME":
            income += movement.amount
        elif movement.type in ("EXPENSE", "CARD_PURCHASE"):
            expenses += movement.amount
            if movement.category_id is not None and movement.category_name is not None:
                key = (movement.category_id, movement.category_name)
                category_expenses[key] = category_expenses.get(key, ZERO) + movement.amount

    return PeriodSummary(income, expenses, category_expenses)


def calculate_invoice_amounts(
    movements: Iterable[FinancialMovement],
    invoice_id: UUID,
    closing_date: date,
    due_date: date,
    as_of: date,
    opening_balance: Decimal = ZERO,
) -> InvoiceAmounts:
    total = opening_balance
    paid_amount = ZERO
    for movement in movements:
        if movement.status != "CONFIRMED" or movement.invoice_id != invoice_id:
            continue
        if movement.type == "CARD_PURCHASE":
            total += movement.amount
        elif movement.type == "CARD_PAYMENT":
            paid_amount += movement.amount

    outstanding = max(total - paid_amount, ZERO)
    if total > ZERO and outstanding == ZERO:
        invoice_status: InvoiceStatus = "PAID"
    elif as_of > due_date and outstanding > ZERO:
        invoice_status = "OVERDUE"
    elif paid_amount > ZERO and outstanding > ZERO:
        invoice_status = "PARTIALLY_PAID"
    elif as_of > closing_date:
        invoice_status = "CLOSED"
    else:
        invoice_status = "OPEN"
    return InvoiceAmounts(total, paid_amount, outstanding, invoice_status)


def calculate_card_limit(
    credit_limit: Decimal,
    invoices: Iterable[tuple[date, InvoiceAmounts]],
) -> CardLimitSummary:
    used_limit = ZERO
    due_dates: list[date] = []
    for due_date, amounts in invoices:
        used_limit += amounts.outstanding
        if amounts.outstanding > ZERO:
            due_dates.append(due_date)
    return CardLimitSummary(
        used_limit=used_limit,
        available_limit=credit_limit - used_limit,
        next_due_date=min(due_dates) if due_dates else None,
    )

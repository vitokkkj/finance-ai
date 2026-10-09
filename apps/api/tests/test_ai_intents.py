from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.ai_intents import format_brl, parse_manual_expense
from app.models import Account, Category


def _account(name: str = "Sicredi", *, active: bool = True) -> Account:
    return Account(
        id=uuid4(),
        user_id=uuid4(),
        name=name,
        type="CHECKING",
        currency="BRL",
        opening_balance=None,
        opening_balance_date=None,
        is_active=active,
    )


def _category(name: str, *, active: bool = True) -> Category:
    return Category(
        id=uuid4(),
        user_id=uuid4(),
        name=name,
        type="EXPENSE",
        archived_at=None if active else date(2026, 1, 1),
    )


@pytest.mark.parametrize(
    ("content", "amount", "category_name", "description"),
    [
        (
            "Gastei 87 reais em combustível na moto.",
            "87.00",
            "Combustível",
            "Combustível na moto",
        ),
        ("Gastei 34 reais em alimentação.", "34.00", "Alimentação", "Alimentação"),
        ("botei 100 de gasolina hj", "100.00", "Combustível", "Gasolina"),
    ],
)
def test_clear_expense_phrases_map_to_existing_account_and_category(
    content: str, amount: str, category_name: str, description: str
) -> None:
    account = _account()
    fuel = _category("Combustível")
    food = _category("Alimentação")

    result = parse_manual_expense(content, [account], [fuel, food], date(2026, 10, 9))

    assert result.kind == "READY"
    assert result.arguments == {
        "account_id": str(account.id),
        "category_id": str(fuel.id if category_name == "Combustível" else food.id),
        "movement_type": "EXPENSE",
        "description": description,
        "amount": amount,
        "occurred_at": "2026-10-09",
    }


def test_expense_amount_uses_decimal_and_brazilian_grouping() -> None:
    account = _account()
    category = _category("Alimentação")

    result = parse_manual_expense(
        "Gastei R$ 1.234,56 em alimentação ontem.",
        [account],
        [category],
        date(2026, 10, 9),
    )

    assert result.kind == "READY"
    assert result.arguments is not None
    assert result.arguments["amount"] == "1234.56"
    assert result.arguments["occurred_at"] == "2026-10-08"
    assert format_brl(Decimal(result.arguments["amount"])) == "1.234,56"


def test_missing_category_or_ambiguous_account_asks_instead_of_guessing() -> None:
    account = _account()
    food = _category("Alimentação")

    missing_category = parse_manual_expense(
        "Gastei R$ 200.", [account], [food], date(2026, 10, 9)
    )
    ambiguous_account = parse_manual_expense(
        "Gastei R$ 200 em alimentação.",
        [account, _account("Inter")],
        [food],
        date(2026, 10, 9),
    )

    assert missing_category.kind == "CLARIFY"
    assert "categoria" in (missing_category.message or "").casefold()
    assert ambiguous_account.kind == "CLARIFY"
    assert "conta" in (ambiguous_account.message or "").casefold()


def test_card_context_and_correction_are_not_treated_as_new_expenses() -> None:
    account = _account()
    category = _category("Alimentação")

    card = parse_manual_expense(
        "Gastei R$ 100 no cartão de crédito em alimentação.",
        [account],
        [category],
        date(2026, 10, 9),
    )
    correction = parse_manual_expense(
        "Gastei R$ 100 em alimentação. Na verdade foram R$ 120.",
        [account],
        [category],
        date(2026, 10, 9),
    )

    assert card.kind == "CLARIFY"
    assert "cartão" in (card.message or "").casefold()
    assert correction.kind == "NOT_APPLICABLE"


def test_archived_categories_are_not_selected() -> None:
    result = parse_manual_expense(
        "Gastei R$ 34 em alimentação.",
        [_account()],
        [_category("Alimentação", active=False)],
        date(2026, 10, 9),
    )

    assert result.kind == "CLARIFY"
    assert "categoria" in (result.message or "").casefold()

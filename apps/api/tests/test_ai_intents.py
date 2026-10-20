from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.ai_intents import (
    format_brl,
    is_manual_expense_candidate,
    parse_manual_expense,
    parse_manual_recurrence,
    parse_month_forecast_period,
    suggest_expense_category_name,
)
from app.models import Account, Category


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Quais são meus gastos previstos para novembro?", (2026, 11)),
        ("O que tenho que pagar em janeiro?", (2027, 1)),
        ("Quais contas a pagar em 02/2027?", (2027, 2)),
        ("Previsão deste mês", (2026, 10)),
        ("Contas previstas para o próximo mês", (2026, 11)),
    ],
)
def test_month_forecast_query_resolves_requested_period(
    content: str, expected: tuple[int, int]
) -> None:
    assert parse_month_forecast_period(content, date(2026, 10, 12)) == expected


@pytest.mark.parametrize(
    "content",
    [
        "Quanto gastei em novembro?",
        "Mostre meu saldo em novembro",
        "Quais são meus gastos previstos para novembro e dezembro?",
        "O que tenho que pagar neste mês e no próximo mês?",
        "O que tenho que pagar em novembro e no próximo mês?",
    ],
)
def test_month_forecast_query_does_not_capture_other_or_ambiguous_requests(content: str) -> None:
    assert parse_month_forecast_period(content, date(2026, 10, 12)) is None


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


def test_explicit_amount_first_expense_uses_the_named_category_without_model_lookup() -> None:
    account = _account()
    lunch = _category("Lanche")
    food = _category("Alimentação")

    result = parse_manual_expense(
        "15 em Bolo, lançar em Lanche",
        [account],
        [lunch, food],
        date(2026, 10, 19),
    )

    assert result.kind == "READY"
    assert result.arguments == {
        "account_id": str(account.id),
        "category_id": str(lunch.id),
        "movement_type": "EXPENSE",
        "description": "Bolo",
        "amount": "15.00",
        "occurred_at": "2026-10-19",
    }


def test_amount_first_expense_still_clarifies_ambiguous_account_and_card() -> None:
    lunch = _category("Lanche")
    content = "R$ 15,50 em Bolo, lançar na categoria Lanche"

    ambiguous_account = parse_manual_expense(
        content,
        [_account(), _account("Inter")],
        [lunch],
        date(2026, 10, 19),
    )
    card_purchase = parse_manual_expense(
        "15 no cartão em Bolo, lançar em Lanche",
        [_account()],
        [lunch],
        date(2026, 10, 19),
    )

    assert ambiguous_account.kind == "CLARIFY"
    assert ambiguous_account.clarification_field == "account"
    assert card_purchase.kind == "CLARIFY"
    assert card_purchase.clarification_field == "payment_method"


def test_amount_first_message_requires_an_explicit_category_command() -> None:
    assert is_manual_expense_candidate("15 em Bolo, lançar em Lanche")
    assert not is_manual_expense_candidate("15 em Bolo")


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


def test_education_expense_terms_match_or_suggest_existing_category_name() -> None:
    account = _account()
    category = _category("Educação")
    result = parse_manual_expense(
        "Gastei R$ 80 no curso de inglês.",
        [account],
        [category],
        date(2026, 10, 9),
    )

    assert result.kind == "READY"
    assert result.arguments is not None
    assert result.arguments["category_id"] == str(category.id)
    assert suggest_expense_category_name("Gastei R$ 80 no curso de inglês") == "Educação"


def test_clear_fixed_expense_request_parses_month_year_and_payment_notes() -> None:
    account = _account()
    category = _category("Educação")
    message = (
        "Crie a categoria Educação, e registre um gasto fixo, começando por 11/26 "
        "e finalizando até 04/28, gasto fixo programado de 282 reais, que é pago via pix, "
        "vencimento dia 08 de todo mês."
    )

    result = parse_manual_recurrence(
        message,
        [account],
        [category],
        date(2026, 10, 10),
    )

    assert result is not None
    assert result.category_to_create is None
    assert result.arguments == {
        "account_id": str(account.id),
        "category_id": str(category.id),
        "movement_type": "EXPENSE",
        "description": "Gasto fixo de Educação",
        "amount": "282.00",
        "frequency": "MONTHLY",
        "interval": 1,
        "starts_on": "2026-11-08",
        "ends_on": "2028-04-08",
        "notes": "Pago via Pix; Vencimento dia 08",
    }


def test_explicit_new_recurrence_category_is_returned_for_creation() -> None:
    message = (
        "Crie a categoria Educação, e programe um gasto fixo de 282 reais "
        "começando por 11/26 e finalizando até 04/28, vencimento dia 08 todo mês."
    )

    result = parse_manual_recurrence(message, [_account()], [], date(2026, 10, 10))

    assert result is not None
    assert result.category_to_create == "Educação"
    assert result.arguments["category_id"] == ""
    assert result.arguments["description"] == "Gasto fixo de Educação"


def test_recurrence_parser_does_not_guess_ambiguous_account_or_missing_category() -> None:
    message = (
        "Programe um gasto fixo de R$ 282 por mês, começando em 11/26, "
        "todo dia 08."
    )

    ambiguous_account = parse_manual_recurrence(
        message,
        [_account("Sicredi"), _account("Inter")],
        [_category("Educação")],
        date(2026, 10, 10),
    )
    missing_category = parse_manual_recurrence(
        message,
        [_account()],
        [_category("Alimentação")],
        date(2026, 10, 10),
    )

    assert ambiguous_account is None
    assert missing_category is None

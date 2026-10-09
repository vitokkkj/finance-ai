from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.models import Account, Category

ExpenseDecisionKind = Literal["NOT_APPLICABLE", "CLARIFY", "READY"]
ExpenseClarificationField = Literal["payment_method", "amount", "date", "category", "account"]

_ENTRY_START = re.compile(r"^(?:eu\s+)?(?:gastei|botei)\b", re.IGNORECASE)
_MONEY = re.compile(
    r"(?<![\w])(?:r\$\s*)?(?P<value>"
    r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:[,.]\d{1,2})?"
    r")(?:\s*(?:reais|real))?",
    re.IGNORECASE,
)
_EXPLICIT_DATE = re.compile(r"(?<!\d)(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})(?!\d)")
_ISO_DATE = re.compile(r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?!\d)")
_CATEGORY_SYNONYMS = (
    frozenset({"combustivel", "gasolina", "abastecimento"}),
    frozenset(
        {
            "alimentacao",
            "comida",
            "refeicao",
            "refeicoes",
            "lanche",
            "lanches",
            "croissant",
            "pao",
            "padaria",
            "salgado",
            "pizza",
            "bolo",
            "cafe",
            "almoco",
            "jantar",
            "restaurante",
            "lanchonete",
            "mercado",
            "supermercado",
        }
    ),
    frozenset({"pets", "pet", "veterinario", "veterinaria", "racao", "petshop", "banho", "tosa"}),
    frozenset(
        {
            "saude",
            "farmacia",
            "remedio",
            "medicamento",
            "consulta",
            "exame",
            "dentista",
            "medico",
        }
    ),
    frozenset({"transporte", "uber", "taxi", "onibus", "metro", "estacionamento", "pedagio"}),
)
_CATEGORY_SUGGESTIONS = (
    ("Combustível", frozenset({"combustivel", "gasolina", "abastecimento"})),
    (
        "Alimentação",
        frozenset(
            {
                "alimentacao",
                "comida",
                "refeicao",
                "refeicoes",
                "lanche",
                "lanches",
                "croissant",
                "pao",
                "padaria",
                "salgado",
                "pizza",
                "bolo",
                "cafe",
                "almoco",
                "jantar",
                "restaurante",
                "lanchonete",
                "mercado",
                "supermercado",
            }
        ),
    ),
    (
        "Pets",
        frozenset(
            {"pets", "pet", "veterinario", "veterinaria", "racao", "petshop", "banho", "tosa"}
        ),
    ),
    (
        "Saúde",
        frozenset(
            {
                "saude",
                "farmacia",
                "remedio",
                "medicamento",
                "consulta",
                "exame",
                "dentista",
                "medico",
            }
        ),
    ),
    (
        "Transporte",
        frozenset(
            {"transporte", "uber", "taxi", "onibus", "metro", "estacionamento", "pedagio"}
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ExpenseDecision:
    kind: ExpenseDecisionKind
    message: str | None = None
    arguments: dict[str, str] | None = None
    amount: Decimal | None = None
    description: str | None = None
    clarification_field: ExpenseClarificationField | None = None


def is_manual_expense_candidate(content: str) -> bool:
    return _ENTRY_START.match(content.strip()) is not None


def parse_manual_expense(
    content: str,
    accounts: Sequence[Account],
    categories: Sequence[Category],
    today: date,
    *,
    category_hint: str | None = None,
) -> ExpenseDecision:
    original = content.strip()
    start_match = _ENTRY_START.match(original)
    if start_match is None:
        return ExpenseDecision("NOT_APPLICABLE")

    normalized_content = _normalize(original)
    if any(term in normalized_content for term in ("na verdade", "errei", "corrigindo")):
        return ExpenseDecision("NOT_APPLICABLE")

    if _contains_word(normalized_content, {"cartao", "credito"}):
        return ExpenseDecision(
            "CLARIFY",
            "Esse gasto foi feito no cartão de crédito ou saiu de uma conta?",
            clarification_field="payment_method",
        )

    tail = original[start_match.end() :]
    money_match = _MONEY.search(tail)
    if money_match is None:
        return ExpenseDecision(
            "CLARIFY", "Qual foi o valor desse gasto?", clarification_field="amount"
        )

    raw_amount = money_match.group("value")
    remainder = tail[money_match.end() :]
    cents_match = re.match(r"\s+e\s+(?P<cents>\d{1,2})\s+centavos\b", remainder, re.IGNORECASE)
    if cents_match is not None:
        remainder = remainder[cents_match.end() :]
    elif re.match(r"\s*[,.]\d", remainder):
        return ExpenseDecision(
            "CLARIFY",
            "Informe o valor com no máximo duas casas decimais, por exemplo R$ 87,50.",
            clarification_field="amount",
        )

    amount = _parse_amount(raw_amount, cents_match.group("cents") if cents_match else None)
    if amount is None:
        return ExpenseDecision(
            "CLARIFY",
            "Não consegui identificar um valor válido para o gasto.",
            clarification_field="amount",
        )

    occurred_at = _parse_date(original, today)
    if occurred_at is None:
        return ExpenseDecision(
            "CLARIFY",
            "Qual foi a data do gasto? Pode informar no formato DD/MM/AAAA.",
            clarification_field="date",
        )

    active_categories = [
        category
        for category in categories
        if category.type == "EXPENSE" and category.archived_at is None
    ]
    if not active_categories:
        return ExpenseDecision(
            "CLARIFY",
            "Você ainda não cadastrou categorias de despesa.",
            clarification_field="category",
            amount=amount,
        )
    category = _match_category(normalized_content, active_categories, category_hint)
    if category is None:
        options = _list_names(category.name for category in active_categories)
        message = "Em qual categoria devo classificar esse gasto?"
        if options:
            message += f" Suas categorias disponíveis incluem {options}."
        return ExpenseDecision(
            "CLARIFY",
            message,
            clarification_field="category",
            amount=amount,
        )

    active_accounts = [account for account in accounts if account.is_active]
    mentioned_accounts = [
        account
        for account in active_accounts
        if _contains_phrase(normalized_content, _normalize(account.name))
    ]
    if len(mentioned_accounts) == 1:
        account = mentioned_accounts[0]
    elif len(mentioned_accounts) > 1:
        return ExpenseDecision(
            "CLARIFY",
            "Mencione apenas uma conta para este gasto.",
            clarification_field="account",
        )
    elif len(active_accounts) == 1:
        account = active_accounts[0]
    elif not active_accounts:
        return ExpenseDecision(
            "CLARIFY",
            "Não encontrei uma conta ativa para registrar esse gasto. Cadastre uma conta primeiro.",
            clarification_field="account",
        )
    else:
        options = _list_names(account.name for account in active_accounts)
        return ExpenseDecision(
            "CLARIFY",
            f"Em qual conta devo registrar esse gasto? Suas contas incluem {options}.",
            clarification_field="account",
        )

    description = (
        _make_description(
            tail[: money_match.start()] + remainder,
            active_accounts,
        )
        or category.name
    )
    arguments = {
        "account_id": str(account.id),
        "category_id": str(category.id),
        "movement_type": "EXPENSE",
        "description": description,
        "amount": format(amount, ".2f"),
        "occurred_at": occurred_at.isoformat(),
    }
    return ExpenseDecision("READY", arguments=arguments, amount=amount, description=description)


def format_brl(amount: Decimal) -> str:
    whole, cents = format(amount.quantize(Decimal("0.01")), ".2f").split(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"{grouped},{cents}"


def suggest_expense_category_name(content: str) -> str | None:
    """Return a category suggestion only when a known expense phrase is unambiguous."""
    normalized = _normalize(content)
    matches = [
        name
        for name, synonyms in _CATEGORY_SUGGESTIONS
        if any(_contains_word(normalized, {synonym}) for synonym in synonyms)
    ]
    return matches[0] if len(matches) == 1 else None


def _parse_amount(raw: str, cents: str | None) -> Decimal | None:
    normalized = raw
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", normalized):
        normalized = normalized.replace(".", "")
    try:
        amount = Decimal(normalized)
        if cents is not None:
            amount += Decimal(cents) / Decimal("100")
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= Decimal("0") or amount > Decimal("999999999999.99"):
        return None
    return amount


def _parse_date(content: str, today: date) -> date | None:
    normalized = _normalize(content)
    if _contains_word(normalized, {"amanha", "anteontem"}):
        if _contains_word(normalized, {"anteontem"}):
            return today - timedelta(days=2)
        return None
    if _contains_word(normalized, {"ontem"}):
        return today - timedelta(days=1)

    explicit = _EXPLICIT_DATE.search(content)
    if explicit is not None:
        try:
            return date(
                int(explicit.group("year")),
                int(explicit.group("month")),
                int(explicit.group("day")),
            )
        except ValueError:
            return None

    iso = _ISO_DATE.search(content)
    if iso is not None:
        try:
            return date(
                int(iso.group("year")),
                int(iso.group("month")),
                int(iso.group("day")),
            )
        except ValueError:
            return None

    unsupported_periods = ("mes passado", "semana passada", "ano passado")
    if any(period in normalized for period in unsupported_periods):
        return None
    return today


def _match_category(
    message: str,
    categories: Sequence[Category],
    category_hint: str | None = None,
) -> Category | None:
    normalized_hint = _normalize(category_hint) if category_hint else ""
    if normalized_hint:
        hinted_matches = [
            category
            for category in categories
            if _contains_phrase(normalized_hint, _normalize(category.name))
        ]
        if len(hinted_matches) == 1:
            return hinted_matches[0]
        if len(hinted_matches) > 1:
            return None

        hint_words = set(normalized_hint.split())
        for synonyms in _CATEGORY_SYNONYMS:
            if hint_words.intersection(synonyms):
                matches = [
                    category for category in categories if _normalize(category.name) in synonyms
                ]
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    return None

    direct_matches = [
        category for category in categories if _contains_phrase(message, _normalize(category.name))
    ]
    if len(direct_matches) == 1:
        return direct_matches[0]
    if len(direct_matches) > 1:
        return None

    words = set(message.split())
    for synonyms in _CATEGORY_SYNONYMS:
        if words.intersection(synonyms):
            matches = [category for category in categories if _normalize(category.name) in synonyms]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                return None
    return None


def _make_description(text: str, accounts: list[Account]) -> str:
    description = text
    for account in accounts:
        if account.name.strip():
            description = re.sub(re.escape(account.name), " ", description, flags=re.IGNORECASE)
    description = re.sub(r"\b(?:hoje|ontem|hj)\b", " ", description, flags=re.IGNORECASE)
    description = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b", " ", description)
    description = re.sub(r"^\s*(?:em|de|do|da|no|na|com)\s+", "", description, flags=re.IGNORECASE)
    description = re.sub(r"[^\w\s'-]", " ", description, flags=re.UNICODE)
    description = " ".join(description.split()).strip(" '-")
    if description:
        description = description[0].upper() + description[1:]
    return description[:200]


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    without_marks = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def _contains_phrase(value: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {value} "


def _contains_word(value: str, words: set[str]) -> bool:
    return bool(set(value.split()).intersection(words))


def _list_names(names: Iterable[str]) -> str:
    values = list(names)
    visible = [str(value) for value in values[:5]]
    if len(values) > 5:
        visible.append("outras")
    return ", ".join(visible)

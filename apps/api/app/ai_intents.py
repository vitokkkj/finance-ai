from __future__ import annotations

import re
import unicodedata
from calendar import monthrange
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
_MONTH_YEAR = re.compile(r"(?<!\d)(?P<month>0?[1-9]|1[0-2])/(?P<year>\d{2}|\d{4})(?!\d)")
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
    frozenset(
        {
            "educacao",
            "escola",
            "curso",
            "cursos",
            "faculdade",
            "universidade",
            "matricula",
        }
    ),
    frozenset(
        {
            "moradia",
            "aluguel",
            "condominio",
            "iptu",
            "energia",
            "eletricidade",
            "agua",
            "internet",
            "telefone",
        }
    ),
    frozenset(
        {
            "assinaturas",
            "assinatura",
            "streaming",
            "netflix",
            "spotify",
            "mensalidade streaming",
        }
    ),
    frozenset(
        {
            "lazer",
            "cinema",
            "show",
            "passeio",
            "jogos",
            "viagem",
            "viagens",
        }
    ),
    frozenset(
        {
            "compras",
            "roupa",
            "roupas",
            "vestuario",
            "calcado",
            "calcados",
        }
    ),
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
    (
        "Educação",
        frozenset(
            {
                "educacao",
                "escola",
                "curso",
                "cursos",
                "faculdade",
                "universidade",
                "matricula",
            }
        ),
    ),
    (
        "Moradia",
        frozenset(
            {
                "moradia",
                "aluguel",
                "condominio",
                "iptu",
                "energia",
                "eletricidade",
                "agua",
                "internet",
                "telefone",
            }
        ),
    ),
    (
        "Assinaturas",
        frozenset(
            {
                "assinaturas",
                "assinatura",
                "streaming",
                "netflix",
                "spotify",
                "mensalidade streaming",
            }
        ),
    ),
    (
        "Lazer",
        frozenset({"lazer", "cinema", "show", "passeio", "jogos", "viagem", "viagens"}),
    ),
    (
        "Compras",
        frozenset({"compras", "roupa", "roupas", "vestuario", "calcado", "calcados"}),
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


@dataclass(frozen=True, slots=True)
class RecurrenceDecision:
    arguments: dict[str, object]
    category_to_create: str | None = None


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


def parse_manual_recurrence(
    content: str,
    accounts: Sequence[Account],
    categories: Sequence[Category],
    today: date,
) -> RecurrenceDecision | None:
    """Parse only fully specified recurring expenses; ambiguous requests go to the AI."""
    original = content.strip()
    normalized = _normalize(original)
    if not _contains_word(normalized, {"gasto", "despesa"}):
        return None
    if not any(
        term in normalized
        for term in ("fixo", "fixa", "recorrente", "programado", "programada", "todo mes", "mensal")
    ):
        return None

    frequency: str | None = None
    if any(term in normalized for term in ("todo mes", "todos os meses", "mensal")):
        frequency = "MONTHLY"
    elif any(term in normalized for term in ("toda semana", "todas as semanas", "semanal")):
        frequency = "WEEKLY"
    elif any(term in normalized for term in ("todo dia", "todos os dias", "diario")):
        frequency = "DAILY"
    elif any(term in normalized for term in ("todo ano", "todos os anos", "anual")):
        frequency = "YEARLY"
    interval_match = re.search(
        r"\ba cada\s+(?P<interval>\d+)\s+(?P<unit>dias?|semanas?|meses?|anos?)\b",
        normalized,
    )
    interval = 1
    if interval_match is not None:
        unit = interval_match.group("unit")
        frequency = (
            "DAILY" if unit.startswith("dia") else
            "WEEKLY" if unit.startswith("semana") else
            "MONTHLY" if unit.startswith("mes") else
            "YEARLY"
        )
        interval = int(interval_match.group("interval"))
    if frequency is None or interval < 1 or interval > 365:
        return None

    explicit_dates = list(_EXPLICIT_DATE.finditer(original))
    month_years = list(_MONTH_YEAR.finditer(original)) if not explicit_dates else []
    if explicit_dates:
        if len(explicit_dates) > 2:
            return None
        try:
            parsed_dates = [
                date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
                for match in explicit_dates
            ]
        except ValueError:
            return None
        starts_on = parsed_dates[0]
        ends_on = parsed_dates[1] if len(parsed_dates) == 2 else None
    elif month_years:
        if len(month_years) > 2:
            return None
        parsed_months: list[tuple[int, int]] = []
        for match in month_years:
            year_text = match.group("year")
            year = int(year_text)
            if len(year_text) == 2:
                year += 2000
            parsed_months.append((year, int(match.group("month"))))
        if len(parsed_months) == 1 and any(
            term in normalized for term in ("ate", "finaliz", "termina")
        ):
            return None
    else:
        return None

    day_matches = {
        int(value)
        for value in re.findall(r"\bdia\s+(\d{1,2})\b", normalized)
    }
    if len(day_matches) > 1:
        return None
    if explicit_dates:
        due_day = next(iter(day_matches), starts_on.day)
        if due_day != starts_on.day:
            return None
        if len(parsed_dates) == 2 and parsed_dates[1].day != due_day:
            return None
    else:
        due_day = next(iter(day_matches), 0)
        if due_day < 1 or due_day > 31:
            return None
        starts_on = _date_in_month(parsed_months[0][0], parsed_months[0][1], due_day)
        ends_on = (
            _date_in_month(parsed_months[1][0], parsed_months[1][1], due_day)
            if len(parsed_months) == 2
            else None
        )
    if starts_on < today or (ends_on is not None and ends_on < starts_on):
        return None

    amount_text = _EXPLICIT_DATE.sub(" ", original)
    amount_text = _MONTH_YEAR.sub(" ", amount_text)
    amount_text = re.sub(
        r"\ba cada\s+\d+\s+(?:dias?|semanas?|meses?|anos?)\b",
        " ",
        amount_text,
        flags=re.IGNORECASE,
    )
    amount_text = re.sub(r"\bdia\s+\d{1,2}\b", " ", amount_text, flags=re.IGNORECASE)
    amount_matches: list[tuple[re.Match[str], str | None]] = []
    for match in _MONEY.finditer(amount_text):
        prefix = _normalize(amount_text[max(0, match.start() - 18) : match.start()])
        has_currency = "r$" in amount_text[max(0, match.start() - 3) : match.start()].casefold()
        has_amount_context = bool(re.search(r"\b(?:de|por|valor)\s*$", prefix))
        has_unit = bool(re.match(r"\s*(?:reais|real)\b", amount_text[match.end() :], re.IGNORECASE))
        if has_currency or has_amount_context or has_unit:
            amount_matches.append((match, None))
    if len(amount_matches) != 1:
        return None
    amount_match = amount_matches[0][0]
    amount = _parse_amount(amount_match.group("value"), None)
    if amount is None:
        return None

    active_accounts = [account for account in accounts if account.is_active]
    mentioned_accounts = [
        account for account in active_accounts
        if _contains_phrase(normalized, _normalize(account.name))
    ]
    if len(mentioned_accounts) == 1:
        account = mentioned_accounts[0]
    elif len(mentioned_accounts) == 0 and len(active_accounts) == 1:
        account = active_accounts[0]
    else:
        return None

    active_categories = [
        category for category in categories
        if category.type == "EXPENSE" and category.archived_at is None
    ]
    category_to_create = _explicit_category_creation_name(original)
    category = None
    if category_to_create:
        category = next(
            (
                item
                for item in active_categories
                if _normalize(item.name) == _normalize(category_to_create)
            ),
            None,
        )
        if category is None and any(
            item.type == "EXPENSE" and _normalize(item.name) == _normalize(category_to_create)
            for item in categories
        ):
            return None
    else:
        matches = [
            item for item in active_categories
            if _contains_phrase(normalized, _normalize(item.name))
        ]
        if len(matches) != 1:
            return None
        category = matches[0]

    if category_to_create and len(category_to_create) > 100:
        return None
    if category is None and category_to_create is None:
        return None

    notes: list[str] = []
    if _contains_word(normalized, {"pix"}):
        notes.append("Pago via Pix")
    notes.append(f"Vencimento dia {due_day:02d}")
    arguments: dict[str, object] = {
        "account_id": str(account.id),
        "category_id": str(category.id) if category is not None else "",
        "movement_type": "EXPENSE",
        "description": (
            f"Gasto fixo de {category.name if category is not None else category_to_create}"
        ),
        "amount": format(amount, ".2f"),
        "frequency": frequency,
        "interval": interval,
        "starts_on": starts_on.isoformat(),
        "ends_on": ends_on.isoformat() if ends_on is not None else None,
        "notes": "; ".join(notes),
    }
    return RecurrenceDecision(
        arguments=arguments,
        category_to_create=category_to_create if category is None else None,
    )


def _date_in_month(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, monthrange(year, month)[1]))


def _explicit_category_creation_name(content: str) -> str | None:
    match = re.search(
        r"\b(?:crie|criar|cadastre|cadastrar|adicione|adicionar)\s+(?:a\s+)?categoria\s+[\"“']?([^\"”',.;\n]+)",
        content,
        re.IGNORECASE,
    )
    if match is None:
        return None
    name = re.split(
        r"\s+e\s+(?=(?:registre|programe|lance|cadastre)\b)",
        match.group(1),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    name = name.strip().strip(" \t\r\n.,!?\"'“”‘’")
    return name or None


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
        if _contains_any_alias(normalized, synonyms)
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

        for synonyms in _CATEGORY_SYNONYMS:
            if _contains_any_alias(normalized_hint, synonyms):
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

    for synonyms in _CATEGORY_SYNONYMS:
        if _contains_any_alias(message, synonyms):
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


def parse_month_forecast_period(content: str, today: date) -> tuple[int, int] | None:
    """Resolve an unambiguous month-specific question about future/pending payments."""
    normalized = _normalize(content)
    if not any(
        marker in f" {normalized} "
        for marker in (
            "previs",
            " a pagar ",
            "tenho que pagar",
            "preciso pagar",
            "devo pagar",
            "o que pago",
            "quanto pago",
        )
    ):
        return None

    month_numbers = {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    month_pattern = "|".join(month_numbers)
    named_months = list(
        re.finditer(rf"\b(?P<name>{month_pattern})\b(?:\s+de\s+(?P<year>20\d{{2}}))?", normalized)
    )
    numeric_months = list(
        re.finditer(
            r"(?<!\d)(?P<month>0?[1-9]|1[0-2])\s*/\s*(?P<year>20\d{2})(?!\d)",
            content,
        )
    )

    current_month_requested = any(
        phrase in normalized for phrase in ("este mes", "neste mes", "mes atual", "mes corrente")
    )
    next_month_requested = any(
        phrase in normalized for phrase in ("proximo mes", "mes que vem")
    )
    if current_month_requested and next_month_requested:
        return None

    if len(named_months) + len(numeric_months) > 1:
        return None
    if (named_months or numeric_months) and (current_month_requested or next_month_requested):
        return None
    if named_months:
        match = named_months[0]
        month = month_numbers[match.group("name")]
        explicit_year = match.group("year")
        year = int(explicit_year) if explicit_year else today.year + (month < today.month)
        return year, month
    if numeric_months:
        match = numeric_months[0]
        return int(match.group("year")), int(match.group("month"))

    if current_month_requested:
        return today.year, today.month
    if next_month_requested:
        next_month = today.month + 1
        return (today.year + 1, 1) if next_month == 13 else (today.year, next_month)
    return None


def _contains_phrase(value: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {value} "


def _contains_word(value: str, words: set[str]) -> bool:
    return bool(set(value.split()).intersection(words))


def _contains_any_alias(value: str, aliases: Iterable[str]) -> bool:
    return any(_contains_phrase(value, alias) for alias in aliases)


def _list_names(names: Iterable[str]) -> str:
    values = list(names)
    visible = [str(value) for value in values[:5]]
    if len(values) > 5:
        visible.append("outras")
    return ", ".join(visible)

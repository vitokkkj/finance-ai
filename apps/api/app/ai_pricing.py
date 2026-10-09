from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

PRICING_PATH = Path(__file__).with_name("ai_pricing.json")


def _decimal_rate(raw: object) -> Decimal | None:
    if not isinstance(raw, (str, int)):
        return None
    try:
        rate = Decimal(str(raw))
    except InvalidOperation:
        return None
    return rate if rate.is_finite() and rate >= 0 else None


def _model_rates(model: str) -> dict[str, object] | None:
    try:
        config = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict) or not isinstance(config.get("models"), dict):
        return None
    rates = config["models"].get(model)
    return cast(dict[str, object], rates) if isinstance(rates, dict) else None


def estimated_cost(
    model: str,
    input_tokens: int | None,
    cached_input_tokens: int | None,
    cache_write_tokens: int | None,
    output_tokens: int | None,
) -> Decimal | None:
    """Calculate a USD estimate from versioned per-million token rates."""
    counts = (input_tokens, cached_input_tokens, cache_write_tokens, output_tokens)
    if any(value is None or value < 0 for value in counts):
        return None
    rates = _model_rates(model)
    if rates is None:
        return None
    input_rate = _decimal_rate(rates.get("input_per_million"))
    cached_rate = _decimal_rate(rates.get("cached_input_per_million"))
    cache_write_rate = _decimal_rate(rates.get("cache_write_per_million"))
    output_rate = _decimal_rate(rates.get("output_per_million"))
    if any(rate is None for rate in (input_rate, cached_rate, cache_write_rate, output_rate)):
        return None
    assert input_tokens is not None
    assert cached_input_tokens is not None
    assert cache_write_tokens is not None
    assert output_tokens is not None
    ordinary_input_tokens = input_tokens - cached_input_tokens - cache_write_tokens
    if ordinary_input_tokens < 0:
        return None
    cost = (
        Decimal(ordinary_input_tokens) * cast(Decimal, input_rate)
        + Decimal(cached_input_tokens) * cast(Decimal, cached_rate)
        + Decimal(cache_write_tokens) * cast(Decimal, cache_write_rate)
        + Decimal(output_tokens) * cast(Decimal, output_rate)
    ) / Decimal(1_000_000)
    return cost

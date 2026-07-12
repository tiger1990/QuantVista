"""Alert-rule validation (QV-047) — pure allow-lists; an invalid rule never reaches the DB.

A rule condition is ``{metric, op, value}``. ``metric`` must be a known score/fundamental field and
``op`` a known comparison, so QV-048's evaluator only ever sees runnable rules (same discipline as
the QV-038 screener allow-list). ``scope``/``channel`` are likewise closed sets. Validation raises
``AlertRuleError`` → the API maps it to a 422.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# Numeric metrics an alert may test — mirrors the screener's fields (score sub-scores + valuation/
# quality ratios). RSI/drift/news metrics are a QV-048 extension of this set.
METRICS: frozenset[str] = frozenset(
    {
        "composite_score",
        "fundamental_score",
        "momentum_score",
        "quality_score",
        "sentiment_score",
        "risk_score",
        "coverage",
        "pe",
        "pb",
        "roe",
        "roce",
        "debt_equity",
    }
)
OPS: frozenset[str] = frozenset({"gte", "lte", "gt", "lt", "eq"})
SCOPES: frozenset[str] = frozenset({"stock", "portfolio"})
CHANNELS: frozenset[str] = frozenset({"email", "in_app"})


class AlertRuleError(Exception):
    """A rule spec outside the allow-list → surfaced as HTTP 422 validation_error."""


@dataclass(frozen=True, slots=True)
class AlertCondition:
    metric: str
    op: str
    value: float


def validate_condition(condition: Mapping[str, object]) -> AlertCondition:
    """Validate + normalize a ``{metric, op, value}`` condition; ``AlertRuleError`` if invalid."""
    metric, op, value = condition.get("metric"), condition.get("op"), condition.get("value")
    if metric not in METRICS:
        raise AlertRuleError(f"unknown metric: {metric!r} (allowed: {sorted(METRICS)})")
    if op not in OPS:
        raise AlertRuleError(f"unknown op: {op!r} (allowed: {sorted(OPS)})")
    # bool is a subclass of int — exclude it explicitly; a threshold must be a real number.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AlertRuleError(f"value must be numeric, got {value!r}")
    return AlertCondition(metric=str(metric), op=str(op), value=float(value))


def validate_scope(scope: str) -> str:
    if scope not in SCOPES:
        raise AlertRuleError(f"unknown scope: {scope!r} (allowed: {sorted(SCOPES)})")
    return scope


def validate_channel(channel: str) -> str:
    if channel not in CHANNELS:
        raise AlertRuleError(f"unknown channel: {channel!r} (allowed: {sorted(CHANNELS)})")
    return channel

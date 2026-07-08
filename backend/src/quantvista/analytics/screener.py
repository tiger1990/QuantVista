"""Screener allow-list DSL (QV-038) — the injection defence.

User-supplied filters/sort are validated against an **allow-list**: the field name is looked up
in ``FIELDS``/``CATEGORICAL`` (KeyError → rejected), the operator in ``NUMERIC_OPS`` — only trusted
column tokens are ever interpolated into SQL, and **every value is a bound parameter**. A malicious
value is therefore data, never SQL. Pure (no DB); unit-tested.
"""

from __future__ import annotations

from collections.abc import Sequence

from quantvista.schemas.screener import FilterClause

# Numeric fields → their (trusted) output-column token in the assembled `screened` projection.
FIELDS: dict[str, str] = {
    "composite_score": "composite_score",
    "fundamental_score": "fundamental_score",
    "momentum_score": "momentum_score",
    "quality_score": "quality_score",
    "sentiment_score": "sentiment_score",
    "risk_score": "risk_score",
    "coverage": "coverage",
    "pe": "pe",
    "pb": "pb",
    "roe": "roe",
    "roce": "roce",
    "debt_equity": "debt_equity",
}
# Categorical fields support equality only.
CATEGORICAL: dict[str, str] = {"sector": "sector", "market_cap_bucket": "market_cap_bucket"}

NUMERIC_OPS: dict[str, str] = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "="}

SORT_FIELDS: frozenset[str] = frozenset(FIELDS) | {"symbol"}

_DEFAULT_SORT = "-composite_score"


class ScreenerError(Exception):
    """A filter/sort spec outside the allow-list → surfaced as HTTP 422 validation_error."""


def build_where(filters: Sequence[FilterClause]) -> tuple[str, dict[str, object]]:
    """Compile validated filters into a parameterized WHERE fragment + bound params (AND-ed)."""
    clauses: list[str] = []
    params: dict[str, object] = {}
    for i, f in enumerate(filters):
        key = f"p{i}"
        if f.field in FIELDS:
            if f.op not in NUMERIC_OPS:
                raise ScreenerError(f"operator '{f.op}' is not allowed on '{f.field}'")
            try:
                params[key] = float(f.value)
            except (TypeError, ValueError) as exc:
                raise ScreenerError(f"field '{f.field}' requires a numeric value") from exc
            clauses.append(f"{FIELDS[f.field]} {NUMERIC_OPS[f.op]} :{key}")
        elif f.field in CATEGORICAL:
            if f.op != "eq":
                raise ScreenerError(f"field '{f.field}' supports only the 'eq' operator")
            params[key] = str(f.value)
            clauses.append(f"{CATEGORICAL[f.field]} = :{key}")
        else:
            raise ScreenerError(f"field '{f.field}' is not screenable")
    return (" AND ".join(clauses) if clauses else "true"), params


def build_order(sort: str | None) -> str:
    """Compile a whitelisted ``sort`` (``-field`` = desc) into an ORDER BY clause (NULLS LAST)."""
    spec = sort or _DEFAULT_SORT
    descending = spec.startswith("-")
    name = spec[1:] if descending else spec
    if name not in SORT_FIELDS:
        raise ScreenerError(f"cannot sort by '{name}'")
    direction = "DESC" if descending else "ASC"
    if name == "symbol":
        return f"symbol {direction}"
    return f"{name} {direction} NULLS LAST, symbol ASC"

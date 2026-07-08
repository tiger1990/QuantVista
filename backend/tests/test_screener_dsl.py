"""Screener allow-list DSL (QV-038) — the injection defence, unit-tested (no DB)."""

from __future__ import annotations

import pytest

from quantvista.analytics.screener import ScreenerError, build_order, build_where
from quantvista.schemas.screener import FilterClause


def fc(field: str, op: str, value: float | str) -> FilterClause:
    return FilterClause(field=field, op=op, value=value)


def test_numeric_filter_builds_a_bound_param() -> None:
    where, params = build_where([fc("composite_score", "gte", 70)])
    assert where == "composite_score >= :p0"
    assert params == {"p0": 70.0}


def test_multiple_filters_are_anded() -> None:
    where, params = build_where([fc("roe", "gte", 15), fc("composite_score", "gte", 70)])
    assert where == "roe >= :p0 AND composite_score >= :p1"
    assert params == {"p0": 15.0, "p1": 70.0}


def test_categorical_equality() -> None:
    where, params = build_where([fc("sector", "eq", "IT")])
    assert where == "sector = :p0"
    assert params == {"p0": "IT"}


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ScreenerError):
        build_where([fc("drop_table", "eq", "x")])


def test_disallowed_operator_is_rejected() -> None:
    with pytest.raises(ScreenerError):
        build_where([fc("sector", "gte", "IT")])  # categorical → eq only
    with pytest.raises(ScreenerError):
        build_where([fc("composite_score", "like", 70)])


def test_injection_value_is_data_never_sql() -> None:
    # A malicious string on a numeric field fails numeric validation.
    with pytest.raises(ScreenerError):
        build_where([fc("composite_score", "gte", "70; DROP TABLE stocks")])
    # On a categorical field it is bound as a literal value — never interpolated into SQL text.
    where, params = build_where([fc("sector", "eq", "IT'; DROP TABLE stocks;--")])
    assert where == "sector = :p0"
    assert params["p0"] == "IT'; DROP TABLE stocks;--"


def test_build_order_whitelist_and_direction() -> None:
    assert build_order(None) == "composite_score DESC NULLS LAST, symbol ASC"
    assert build_order("-roe") == "roe DESC NULLS LAST, symbol ASC"
    assert build_order("pe") == "pe ASC NULLS LAST, symbol ASC"
    assert build_order("symbol") == "symbol ASC"
    with pytest.raises(ScreenerError):
        build_order("-nonexistent")

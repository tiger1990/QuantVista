"""Unit tests for alert-rule validation (QV-047) — pure allow-list, no DB."""

from __future__ import annotations

import pytest

from quantvista.alerts.rules import (
    AlertCondition,
    AlertRuleError,
    validate_channel,
    validate_condition,
    validate_scope,
)


def test_valid_condition() -> None:
    c = validate_condition({"metric": "composite_score", "op": "lt", "value": 50})
    assert c == AlertCondition(metric="composite_score", op="lt", value=50.0)


def test_valid_fundamental_metric() -> None:
    assert validate_condition({"metric": "pe", "op": "gte", "value": 30}).metric == "pe"


@pytest.mark.parametrize(
    "condition",
    [
        {"metric": "market_cap", "op": "lt", "value": 50},  # unknown metric
        {"metric": "composite_score", "op": "between", "value": 50},  # unknown op
        {"metric": "composite_score", "op": "lt", "value": "50"},  # non-numeric value
        {"metric": "composite_score", "op": "lt", "value": True},  # bool is not numeric
        {"op": "lt", "value": 50},  # missing metric
        {"metric": "composite_score", "value": 50},  # missing op
        {"metric": "composite_score", "op": "lt"},  # missing value
    ],
)
def test_invalid_condition_rejected(condition: dict[str, object]) -> None:
    with pytest.raises(AlertRuleError):
        validate_condition(condition)


def test_scope_allow_list() -> None:
    assert validate_scope("stock") == "stock"
    assert validate_scope("portfolio") == "portfolio"
    with pytest.raises(AlertRuleError):
        validate_scope("sector")


def test_channel_allow_list() -> None:
    assert validate_channel("email") == "email"
    assert validate_channel("in_app") == "in_app"
    with pytest.raises(AlertRuleError):
        validate_channel("sms")

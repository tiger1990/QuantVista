"""Unit tests for the pure alert-condition match (QV-048)."""

from __future__ import annotations

import pytest

from quantvista.alerts.evaluation import matches


@pytest.mark.parametrize(
    ("value", "op", "threshold", "expected"),
    [
        (40.0, "lt", 50.0, True),
        (60.0, "lt", 50.0, False),
        (50.0, "lt", 50.0, False),
        (60.0, "gt", 50.0, True),
        (50.0, "gte", 50.0, True),
        (49.9, "gte", 50.0, False),
        (50.0, "lte", 50.0, True),
        (30.0, "eq", 30.0, True),
        (30.0, "eq", 30.1, False),
    ],
)
def test_matches(value: float, op: str, threshold: float, expected: bool) -> None:
    assert matches(value, op, threshold) is expected


def test_none_value_never_matches() -> None:
    # A stock missing the metric (e.g. no fundamentals) must not fire.
    for op in ("lt", "gt", "gte", "lte", "eq"):
        assert matches(None, op, 50.0) is False


def test_unknown_op_never_matches() -> None:
    assert matches(50.0, "between", 50.0) is False

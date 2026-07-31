"""Unit tests for the BacktestSpec allow-list validation (QV-062) — pure, no DB.

The ``spec`` is user JSON persisted as JSONB and later executed by the engine (QV-065), so it is
validated strictly at the edge: closed enum sets, numeric bounds, real dates, ``start < end``, and
``extra="forbid"`` to reject unknown keys.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from quantvista.schemas.backtest import BacktestSpec, SubmitBacktestRequest

_VALID = {
    "type": "factor_strategy",
    "universe": "NIFTY200",
    "rules": {"rank_by": "composite", "top_n": 20, "rebalance": "monthly"},
    "start": "2018-01-01",
    "end": "2020-12-31",
    "costs_bps": 15,
    "benchmark": "NIFTY200_TRI",
}


def test_valid_spec_parses() -> None:
    spec = BacktestSpec.model_validate(_VALID)
    assert spec.rules.top_n == 20
    assert spec.start == date(2018, 1, 1)
    assert spec.costs_bps == 15


def test_submit_request_wraps_spec() -> None:
    req = SubmitBacktestRequest.model_validate({"spec": _VALID})
    assert req.spec.universe == "NIFTY200"


@pytest.mark.parametrize(
    "patch",
    [
        {"type": "day_trading"},  # bad enum
        {"universe": "SP500"},  # bad enum
        {"rules": {"rank_by": "astrology", "top_n": 20, "rebalance": "monthly"}},  # bad rank_by
        {"rules": {"rank_by": "composite", "top_n": 0, "rebalance": "monthly"}},  # top_n < 1
        {"rules": {"rank_by": "composite", "top_n": 999, "rebalance": "monthly"}},  # top_n > 200
        {"rules": {"rank_by": "composite", "top_n": 20, "rebalance": "hourly"}},  # bad rebalance
        {"costs_bps": -1},  # below bound
        {"costs_bps": 1000},  # above bound
        {"start": "2021-01-01", "end": "2020-01-01"},  # start >= end
        {"bogus": "x"},  # unknown key (extra=forbid)
    ],
)
def test_invalid_specs_rejected(patch: dict[str, object]) -> None:
    body = {**_VALID, **patch}
    with pytest.raises(ValidationError):
        BacktestSpec.model_validate(body)


def test_range_days_for_entitlement_gate() -> None:
    # The handler gates a >366-day range behind `backtest_full`; the spec exposes the dates for it.
    spec = BacktestSpec.model_validate(_VALID)
    assert (spec.end - spec.start).days > 366  # 2018→2020 is a "full" range


# --- custom basket (QV-071 follow-up) ---------------------------------------


def _basket(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": "custom_basket",
        "universe": "NIFTY200",
        "rules": {"rebalance": "monthly"},
        "symbols": ["TCS", "INFY"],
        "start": "2025-01-01",
        "end": "2025-12-31",
    }
    base.update(over)
    return base


def test_custom_basket_accepts_a_symbol_list_without_ranking_fields() -> None:
    spec = BacktestSpec.model_validate(_basket())
    assert spec.type == "custom_basket"
    assert spec.symbols == ["TCS", "INFY"]
    assert spec.rules.top_n == 20  # defaulted; inert for a basket


def test_custom_basket_normalises_symbols_for_a_stable_hash() -> None:
    spec = BacktestSpec.model_validate(_basket(symbols=[" tcs ", "INFY", "tcs"]))
    assert spec.symbols == ["TCS", "INFY"]  # trimmed, upper-cased, de-duped, order kept


def test_custom_basket_requires_symbols() -> None:
    bad_values: list[object] = [None, []]
    for bad in bad_values:
        with pytest.raises(ValidationError):
            BacktestSpec.model_validate(_basket(symbols=bad))


def test_custom_basket_rejects_blank_and_over_long_lists() -> None:
    with pytest.raises(ValidationError):
        BacktestSpec.model_validate(_basket(symbols=["TCS", "  "]))
    with pytest.raises(ValidationError):
        BacktestSpec.model_validate(_basket(symbols=[f"S{i}" for i in range(51)]))


def test_factor_strategy_rejects_symbols() -> None:
    """Silently ignoring them would let a user think their picks were honoured."""
    with pytest.raises(ValidationError):
        BacktestSpec.model_validate(
            {
                "type": "factor_strategy",
                "rules": {"top_n": 10},
                "symbols": ["TCS"],
                "start": "2025-01-01",
                "end": "2025-12-31",
            }
        )

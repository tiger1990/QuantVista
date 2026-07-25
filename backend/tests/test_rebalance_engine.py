"""Unit tests for the RebalanceEngine (QV-059) — pure compute, no DB.

Validates: drift math, threshold filtering, buy/sell direction, no-target-weight → None,
portfolio_total_drift helper, sorted trades, needs_rebalance flag, equal-weight fallback
in weight basis (degenerate guard from QV-058 compute_portfolio_weights).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from quantvista.portfolio.rebalance import (
    RebalanceEngine,
    portfolio_total_drift,
)

_A = UUID(int=1)
_B = UUID(int=2)
_C = UUID(int=3)

# A=10×100=1000, B=10×300=3000 → market-value weights 0.25 / 0.75
_CLOSES_AB = {_A: Decimal("100"), _B: Decimal("300")}

_TOL = Decimal("0.000002")


def _pos(
    *,
    shares: dict[UUID, str] | None = None,
    target: dict[UUID, str] | None = None,
    ids: tuple[UUID, ...] = (_A, _B),
) -> list[dict[str, object]]:
    out = []
    for sid in ids:
        out.append(
            {
                "stock_id": str(sid),
                "shares": Decimal(shares[sid]) if shares and sid in shares else None,
                "target_weight": Decimal(target[sid]) if target and sid in target else None,
                "symbol": f"SYM{str(sid.int)}",
            }
        )
    return out


def _close(a: Decimal | None, b: float, tol: Decimal = _TOL) -> None:
    assert a is not None and abs(a - Decimal(str(b))) <= tol, (a, b)


# ---------------------------------------------------------------------------
# portfolio_total_drift helper
# ---------------------------------------------------------------------------


def test_portfolio_total_drift_no_targets_returns_none() -> None:
    pos = _pos(shares={_A: "10", _B: "10"})  # no target_weight → None
    assert portfolio_total_drift(pos, _CLOSES_AB) is None


def test_portfolio_total_drift_balanced_is_zero() -> None:
    # current MV weights: A=0.25, B=0.75; targets match exactly → drift = 0
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.25", _B: "0.75"})
    drift = portfolio_total_drift(pos, _CLOSES_AB)
    assert drift == Decimal("0.000000")


def test_portfolio_total_drift_computes_total_variation() -> None:
    # current: A=0.25, B=0.75; target: A=0.50, B=0.50 (normalized)
    # drift = (|0.25-0.50| + |0.75-0.50|) / 2 = (0.25 + 0.25) / 2 = 0.25
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.50", _B: "0.50"})
    drift = portfolio_total_drift(pos, _CLOSES_AB)
    _close(drift, 0.25)


# ---------------------------------------------------------------------------
# RebalanceEngine.suggest
# ---------------------------------------------------------------------------


def test_suggest_returns_none_when_no_targets() -> None:
    pos = _pos(shares={_A: "10", _B: "10"})
    assert RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26") is None


def test_suggest_buy_for_underweight_position() -> None:
    # current: A=0.25, B=0.75; target: A=0.50, B=0.50 → A is underweight → buy A
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.50", _B: "0.50"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26", drift_threshold=Decimal("0.01"))
    assert plan is not None
    directions = {t.stock_id: t.direction for t in plan.trades}
    assert directions[_A] == "buy"
    assert directions[_B] == "sell"


def test_suggest_sell_for_overweight_position() -> None:
    # current: A=0.25, B=0.75; target: A=0.80, B=0.20 → B is overweight → sell B
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.80", _B: "0.20"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26", drift_threshold=Decimal("0.01"))
    assert plan is not None
    direction_b = next(t.direction for t in plan.trades if t.stock_id == _B)
    assert direction_b == "sell"


def test_suggest_filters_positions_within_threshold() -> None:
    # current: A=0.25, B=0.75; target: A=0.24, B=0.76 → drift ~0.01 each
    # With threshold=0.05: neither exceeds → trades is empty
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.24", _B: "0.76"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26", drift_threshold=Decimal("0.05"))
    assert plan is not None
    assert plan.trades == []


def test_suggest_needs_rebalance_true_when_drift_exceeds_threshold() -> None:
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.50", _B: "0.50"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26", drift_threshold=Decimal("0.10"))
    assert plan is not None
    assert plan.needs_rebalance is True  # total_drift=0.25 > 0.10


def test_suggest_needs_rebalance_false_when_balanced() -> None:
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.25", _B: "0.75"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26")
    assert plan is not None
    assert plan.needs_rebalance is False


def test_suggest_trades_sorted_by_abs_delta_descending() -> None:
    # 3 positions; target them all away from current
    closes = {_A: Decimal("100"), _B: Decimal("100"), _C: Decimal("100")}
    pos = _pos(
        shares={_A: "10", _B: "10", _C: "10"},
        target={_A: "0.60", _B: "0.30", _C: "0.10"},
        ids=(_A, _B, _C),
    )
    plan = RebalanceEngine().suggest(pos, closes, "2026-07-26", drift_threshold=Decimal("0.01"))
    assert plan is not None
    deltas = [abs(t.delta_weight) for t in plan.trades]
    assert deltas == sorted(deltas, reverse=True)


def test_suggest_delta_weight_is_target_minus_current() -> None:
    # current: A=0.25, target_norm: A=0.50 → delta = +0.25 (buy)
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.50", _B: "0.50"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26", drift_threshold=Decimal("0.01"))
    assert plan is not None
    a_trade = next(t for t in plan.trades if t.stock_id == _A)
    _close(a_trade.delta_weight, 0.25)
    assert a_trade.delta_weight > 0  # buy


def test_suggest_as_of_date_in_plan() -> None:
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.25", _B: "0.75"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26")
    assert plan is not None
    assert plan.as_of_date == "2026-07-26"


def test_suggest_target_weight_normalized_when_partial() -> None:
    # Only A has target_weight=0.40 (normalized → 1.0); B has no target (excluded)
    # current weights: A=0.25, B=0.75; but only A participates
    # drift for A = |0.25 - 1.0| / 2 = 0.375
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.40"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26", drift_threshold=Decimal("0.01"))
    assert plan is not None
    # A normalized target = 1.0; current_weight = 0.25; delta = +0.75
    a_trade = next((t for t in plan.trades if t.stock_id == _A), None)
    assert a_trade is not None
    assert a_trade.target_weight == Decimal("1.000000")


def test_suggest_decimal_string_fields_are_quantized() -> None:
    pos = _pos(shares={_A: "10", _B: "10"}, target={_A: "0.50", _B: "0.50"})
    plan = RebalanceEngine().suggest(pos, _CLOSES_AB, "2026-07-26", drift_threshold=Decimal("0.01"))
    assert plan is not None
    for trade in plan.trades:
        # All Decimal fields should have exactly 6dp
        assert str(trade.current_weight).split(".")[-1].__len__() == 6
        assert str(trade.target_weight).split(".")[-1].__len__() == 6

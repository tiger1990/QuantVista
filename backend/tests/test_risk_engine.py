"""Unit tests for the RiskEngine (QV-058) — pure compute, no DB.

Validate the metric definitions against an independent numpy reference (vol/Sharpe/Sortino/dd),
the weight-basis decision (market-value vs target fallback), beta coverage renormalization, the
graceful-degradation contract (thin/degenerate series → ``None``, never inf/NaN), and the invariants
(``1/N ≤ HHI ≤ 1``; ``Σw ≈ 1``).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import numpy as np

from quantvista.market_data.returns import ReturnsMatrix
from quantvista.portfolio.risk import RiskEngine, RiskMetrics

_A = UUID(int=1)
_B = UUID(int=2)
_TOL = Decimal("0.000002")  # 6-dp quantize ± 1 ulp


def _positions(
    *, shares: dict[UUID, str] | None = None, target: dict[UUID, str] | None = None
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for sid in (_A, _B):
        out.append(
            {
                "stock_id": str(sid),
                "shares": Decimal(shares[sid]) if shares and sid in shares else None,
                "target_weight": Decimal(target[sid]) if target and sid in target else None,
            }
        )
    return out


def _returns(values: np.ndarray, ids: tuple[UUID, ...] = (_A, _B)) -> ReturnsMatrix:
    return ReturnsMatrix(values=values, stock_ids=ids, dates=(), dropped=())


# Market value: A = 10×100 = 1000, B = 10×300 = 3000 → weights 0.25 / 0.75.
_MV_POS = _positions(shares={_A: "10", _B: "10"})
_CLOSES = {_A: Decimal("100"), _B: Decimal("300")}
_SECTORS = {_A: "IT", _B: "Energy"}
_R = np.array(
    [[0.01, 0.02], [-0.03, -0.02], [0.03, -0.01], [0.00, 0.005], [0.015, 0.00]], dtype=np.float64
)  # portfolio series (w=0.25/0.75) has a genuine negative day → Sortino is defined


def _close(a: Decimal | None, b: float) -> None:
    assert a is not None and abs(a - Decimal(str(b))) <= _TOL, (a, b)


def test_weights_hhi_sector_from_market_value() -> None:
    m = RiskEngine().metrics(_MV_POS, _returns(_R), {_A: Decimal("1.0")}, _SECTORS, _CLOSES)
    # weights 0.25 / 0.75 → HHI = 0.0625 + 0.5625 = 0.625
    assert m.hhi == Decimal("0.625000")
    assert m.sector_exposure == {"IT": Decimal("0.250000"), "Energy": Decimal("0.750000")}


def test_beta_weighted_with_coverage() -> None:
    m = RiskEngine().metrics(
        _MV_POS, _returns(_R), {_A: Decimal("1.0"), _B: Decimal("1.5")}, _SECTORS, _CLOSES
    )
    _close(m.beta, 0.25 * 1.0 + 0.75 * 1.5)  # 1.375
    assert m.beta_coverage.covered == 2 and m.beta_coverage.total == 2
    assert m.beta_coverage.ratio == Decimal("1.000000")


def test_beta_renormalizes_over_covered_names() -> None:
    # B has no beta → beta uses A only, renormalized to weight 1.0 → beta == A's beta.
    m = RiskEngine().metrics(_MV_POS, _returns(_R), {_A: Decimal("1.2")}, _SECTORS, _CLOSES)
    _close(m.beta, 1.2)
    assert m.beta_coverage.covered == 1 and m.beta_coverage.total == 2
    _close(m.beta_coverage.ratio, 0.5)


def test_series_metrics_match_numpy_reference() -> None:
    m = RiskEngine().metrics(_MV_POS, _returns(_R), {_A: Decimal("1.0")}, _SECTORS, _CLOSES)
    w = np.array([0.25, 0.75])
    r_p = _R @ w
    ann_ret = r_p.mean() * 252
    ann_vol = r_p.std(ddof=1) * np.sqrt(252)
    downside = np.sqrt(np.mean(np.minimum(r_p, 0.0) ** 2)) * np.sqrt(252)
    equity = np.concatenate([[1.0], np.cumprod(1.0 + r_p)])
    max_dd = -(equity / np.maximum.accumulate(equity) - 1.0).min()
    _close(m.volatility, ann_vol)
    _close(m.sharpe, ann_ret / ann_vol)
    _close(m.sortino, ann_ret / downside)
    _close(m.max_drawdown, max_dd)
    assert m.max_drawdown is not None and m.max_drawdown >= 0  # positive magnitude


def test_target_weight_fallback_when_no_shares() -> None:
    pos = _positions(target={_A: "0.3", _B: "0.1"})  # no shares → normalize targets → 0.75 / 0.25
    m = RiskEngine().metrics(pos, _returns(_R), {}, _SECTORS, {})
    assert m.sector_exposure == {"IT": Decimal("0.750000"), "Energy": Decimal("0.250000")}


def test_thin_history_series_none_but_beta_and_hhi_present() -> None:
    thin = _returns(np.array([[0.01, 0.02]], dtype=np.float64))  # 1 row < 2 observations
    m = RiskEngine().metrics(
        _MV_POS, thin, {_A: Decimal("1.0"), _B: Decimal("1.0")}, _SECTORS, _CLOSES
    )
    assert (
        m.volatility is None and m.sharpe is None and m.sortino is None and m.max_drawdown is None
    )
    assert m.hhi == Decimal("0.625000")
    _close(m.beta, 1.0)


def test_constant_series_sharpe_sortino_none_not_inf() -> None:
    flat = _returns(np.zeros((6, 2), dtype=np.float64))  # std ≈ 0 → guarded to None
    m = RiskEngine().metrics(_MV_POS, flat, {_A: Decimal("1.0")}, _SECTORS, _CLOSES)
    assert m.sharpe is None and m.sortino is None
    assert m.volatility == Decimal("0.000000")


def test_all_positive_returns_sortino_none() -> None:
    # Varying but all-positive returns → vol > 0 (Sharpe defined) but zero downside → Sortino None.
    up = _returns(
        np.array([[0.01, 0.02], [0.03, 0.01], [0.02, 0.04], [0.05, 0.02]], dtype=np.float64)
    )
    m = RiskEngine().metrics(_MV_POS, up, {_A: Decimal("1.0")}, _SECTORS, _CLOSES)
    assert m.sortino is None  # no negative return → downside deviation ~0 → guarded
    assert m.sharpe is not None  # vol > 0


def test_hhi_and_weight_invariants() -> None:
    m = RiskEngine().metrics(_MV_POS, _returns(_R), {_A: Decimal("1.0")}, _SECTORS, _CLOSES)
    n = 2
    assert Decimal(1) / Decimal(n) <= m.hhi <= Decimal(1)
    assert sum(m.sector_exposure.values()) == Decimal("1.000000")


def test_equal_weight_degenerate_guard() -> None:
    pos = _positions()  # no shares, no targets → equal-weight 0.5 / 0.5
    m = RiskEngine().metrics(pos, _returns(_R), {}, _SECTORS, {})
    assert m.hhi == Decimal("0.500000")  # 0.5² + 0.5²
    assert isinstance(m, RiskMetrics)

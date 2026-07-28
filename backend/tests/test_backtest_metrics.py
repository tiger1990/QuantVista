"""Unit tests for the performance & risk metrics suite (QV-068) — pure math, no DB.

Each metric is checked against a **hand-computed** expected value on a crafted curve/return series,
so a regression in any formula trips immediately. Deterministic + fast.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from quantvista.analytics.backtest_metrics import compute_metrics, empty_metrics

_TRADING_DAYS = 252


def _dates(n: int) -> list[date]:
    return [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]


def _curve_from_returns(rets: list[float]) -> list[float]:
    curve, eq = [1.0], 1.0
    for r in rets:
        eq *= 1.0 + r
        curve.append(eq)
    return curve


def _metrics(
    strat_rets: list[float],
    bench_rets: list[float] | None = None,
    *,
    turnovers: list[float] | None = None,
    exposures: list[float] | None = None,
    rebalance_dates: list[date] | None = None,
) -> dict[str, Any]:
    bench_rets = strat_rets if bench_rets is None else bench_rets
    curve = _curve_from_returns(strat_rets)
    bench_curve = _curve_from_returns(bench_rets)
    sessions = _dates(len(curve))
    exposures = exposures if exposures is not None else [1.0] * len(curve)
    return compute_metrics(
        sessions=sessions,
        curve=curve,
        period_returns=strat_rets,
        turnovers=turnovers if turnovers is not None else [0.5],
        exposures=exposures,
        bench_curve=bench_curve,
        bench_returns=bench_rets,
        rebalance_dates=rebalance_dates if rebalance_dates is not None else [sessions[0]],
        n_rebalances=len(rebalance_dates) if rebalance_dates is not None else 1,
    )


_KEYS = {
    "total_return",
    "cagr",
    "ann_vol",
    "sharpe",
    "sortino",
    "max_drawdown",
    "hit_rate",
    "avg_turnover",
    "avg_exposure",
    "n_rebalances",
    "benchmark_return",
    "excess_return",
    "tracking_error",
    "information_ratio",
    "beta",
    "exposure_series",
}


def test_all_keys_present_and_typed() -> None:
    m = _metrics([0.01, 0.02, -0.01])
    assert set(m) >= _KEYS
    for k in _KEYS - {"n_rebalances", "exposure_series"}:
        assert isinstance(m[k], str)  # Decimal-as-string
    assert isinstance(m["n_rebalances"], int)
    assert isinstance(m["exposure_series"], list)


def test_total_return_and_max_drawdown_exact() -> None:
    # +10%, -50%, +20%  → 1.1, 0.55, 0.66 ; trough drawdown = 0.55/1.1 - 1 = -0.5
    m = _metrics([0.10, -0.50, 0.20])
    assert Decimal(m["total_return"]) == Decimal("-0.34")  # 0.66 - 1
    assert Decimal(m["max_drawdown"]) == Decimal("-0.5")


def test_monotonic_up_has_zero_drawdown_and_positive_sharpe() -> None:
    m = _metrics([0.01] * 10)
    assert Decimal(m["max_drawdown"]) == Decimal("0")
    assert Decimal(m["sharpe"]) > 0
    assert Decimal(m["sortino"]) == Decimal("0")  # no downside → downside_dev 0 → sortino 0


def test_hit_rate_counts_positive_periods() -> None:
    # 3 up, 1 down, 1 flat → non-flat = 4, positive = 3 → 0.75
    m = _metrics([0.01, 0.02, -0.01, 0.0, 0.03])
    assert Decimal(m["hit_rate"]) == Decimal("0.75")


def test_sortino_uses_downside_only() -> None:
    rets = [0.02, -0.01, 0.03, -0.02]
    m = _metrics(rets)
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / len(rets))
    expected = (sum(rets) / len(rets)) / downside * math.sqrt(_TRADING_DAYS)
    assert abs(Decimal(m["sortino"]) - Decimal(str(round(expected, 8)))) < Decimal("0.0000001")


def test_benchmark_identity_gives_beta_one_zero_te_ir() -> None:
    rets = [0.01, -0.02, 0.03, 0.00]
    m = _metrics(rets, rets)  # strategy == benchmark
    assert Decimal(m["excess_return"]) == Decimal("0")
    assert Decimal(m["tracking_error"]) == Decimal("0")
    assert Decimal(m["information_ratio"]) == Decimal("0")
    assert abs(Decimal(m["beta"]) - Decimal("1")) < Decimal("0.0000001")


def test_beta_two_when_strategy_doubles_benchmark() -> None:
    bench = [0.01, -0.02, 0.03, -0.01]
    strat = [2 * r for r in bench]  # perfectly 2x → beta 2
    m = _metrics(strat, bench)
    assert abs(Decimal(m["beta"]) - Decimal("2")) < Decimal("0.0000001")


def test_flat_benchmark_gives_zero_beta() -> None:
    m = _metrics([0.01, -0.01, 0.02], [0.0, 0.0, 0.0])
    assert Decimal(m["beta"]) == Decimal("0")  # var(bench)=0 guard


def test_avg_exposure_and_series() -> None:
    sessions = _dates(4)  # curve has len 4 → 3 returns
    m = compute_metrics(
        sessions=sessions,
        curve=[1.0, 1.0, 1.0, 1.0],
        period_returns=[0.0, 0.0, 0.0],
        turnovers=[0.5, 0.5],
        exposures=[1.0, 0.5, 0.5, 1.0],
        bench_curve=[1.0, 1.0, 1.0, 1.0],
        bench_returns=[0.0, 0.0, 0.0],
        rebalance_dates=[sessions[0], sessions[2]],
        n_rebalances=2,
    )
    assert Decimal(m["avg_exposure"]) == Decimal("0.75")  # mean(1,.5,.5,1)
    assert m["n_rebalances"] == 2
    assert [e["as_of"] for e in m["exposure_series"]] == [
        sessions[0].isoformat(),
        sessions[2].isoformat(),
    ]
    assert m["exposure_series"][0]["exposure"] == "1.0"  # exposure at sessions[0]
    assert m["exposure_series"][1]["exposure"] == "0.5"  # exposure at sessions[2]


def test_avg_turnover() -> None:
    m = _metrics([0.01, 0.01], turnovers=[0.5, 0.3, 0.1])
    assert abs(Decimal(m["avg_turnover"]) - Decimal("0.3")) < Decimal("0.0000001")


def test_empty_metrics_is_valid_and_zeroed() -> None:
    m = empty_metrics()
    assert set(m) >= _KEYS
    assert m["n_rebalances"] == 0
    assert m["exposure_series"] == []
    assert Decimal(m["total_return"]) == Decimal("0")

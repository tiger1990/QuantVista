"""Performance & risk metrics for a backtest (QV-068) — the standard yardsticks (05 §4.6).

A pure function of the equity curve, period returns, turnovers, exposures, and the benchmark, so it
is deterministic + exhaustively unit-testable (no DB). Extends the core set QV-065 computed inline
with Sortino, hit rate, exposure-over-time, and a proper benchmark comparison (tracking error,
information ratio, beta). Every scalar is a **Decimal serialised as a string** — never a raw float.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np

_TRADING_DAYS = 252  # annualisation factor for vol / Sharpe / Sortino / tracking error
_ANNUALISE = float(np.sqrt(_TRADING_DAYS))

_SCALAR_KEYS = (
    "total_return",
    "cagr",
    "ann_vol",
    "sharpe",
    "sortino",
    "max_drawdown",
    "hit_rate",
    "avg_turnover",
    "avg_exposure",
    "benchmark_return",
    "excess_return",
    "tracking_error",
    "information_ratio",
    "beta",
)


def _s(x: float) -> str:
    """Serialise a float metric as a Decimal string (never a raw float on the wire)."""
    return str(Decimal(str(round(float(x), 8))))


def compute_metrics(
    *,
    sessions: Sequence[date],
    curve: Sequence[float],
    period_returns: Sequence[float],
    turnovers: Sequence[float],
    exposures: Sequence[float],
    bench_curve: Sequence[float],
    bench_returns: Sequence[float],
    rebalance_dates: Sequence[date],
    n_rebalances: int,
) -> dict[str, Any]:
    """The full performance & risk suite as Decimal-strings (+ ``n_rebalances`` int + series)."""
    total = curve[-1] - 1.0
    bench = bench_curve[-1] - 1.0
    years = max((sessions[-1] - sessions[0]).days / 365.25, 1e-9)
    cagr = curve[-1] ** (1.0 / years) - 1.0 if curve[-1] > 0 else -1.0

    r = np.asarray(period_returns, dtype=np.float64)
    std = float(r.std(ddof=1)) if r.size > 1 else 0.0
    vol = std * _ANNUALISE
    sharpe = float(r.mean()) / std * _ANNUALISE if std > 0 else 0.0
    downside = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2))) if r.size else 0.0
    sortino = float(r.mean()) / downside * _ANNUALISE if downside > 0 else 0.0

    c = np.asarray(curve, dtype=np.float64)
    max_dd = float((c / np.maximum.accumulate(c) - 1.0).min()) if c.size else 0.0

    positives = int((r > 0).sum())
    active = int((r != 0).sum())
    hit_rate = positives / active if active else 0.0

    # Benchmark comparison — diff / cov aligned on the common periods.
    rb = np.asarray(bench_returns, dtype=np.float64)
    n = min(r.size, rb.size)
    diff = r[:n] - rb[:n]
    te_std = float(diff.std(ddof=1)) if diff.size > 1 else 0.0
    tracking_error = te_std * _ANNUALISE
    information_ratio = float(diff.mean()) / te_std * _ANNUALISE if te_std > 0 else 0.0
    var_b = float(rb[:n].var(ddof=1)) if n > 1 else 0.0
    beta = float(np.cov(r[:n], rb[:n], ddof=1)[0, 1]) / var_b if var_b > 0 else 0.0

    exp = np.asarray(exposures, dtype=np.float64)
    avg_exposure = float(exp.mean()) if exp.size else 0.0

    return {
        "total_return": _s(total),
        "cagr": _s(cagr),
        "ann_vol": _s(vol),
        "sharpe": _s(sharpe),
        "sortino": _s(sortino),
        "max_drawdown": _s(max_dd),
        "hit_rate": _s(hit_rate),
        "avg_turnover": _s(float(np.mean(turnovers)) if turnovers else 0.0),
        "avg_exposure": _s(avg_exposure),
        "n_rebalances": n_rebalances,
        "benchmark_return": _s(bench),
        "excess_return": _s(total - bench),
        "tracking_error": _s(tracking_error),
        "information_ratio": _s(information_ratio),
        "beta": _s(beta),
        "exposure_series": _exposure_series(sessions, exposures, rebalance_dates),
        "equity_curve": _equity_curve(sessions, curve, bench_curve, rebalance_dates),
    }


def _exposure_series(
    sessions: Sequence[date], exposures: Sequence[float], rebalance_dates: Sequence[date]
) -> list[dict[str, str]]:
    """Invested fraction sampled at each rebalance date (compact; daily → the result artifact)."""
    index = {d: i for i, d in enumerate(sessions)}
    out: list[dict[str, str]] = []
    for d in rebalance_dates:
        i = index.get(d)
        if i is not None and i < len(exposures):
            out.append({"as_of": d.isoformat(), "exposure": _s(exposures[i])})
    return out


def _equity_curve(
    sessions: Sequence[date],
    curve: Sequence[float],
    bench_curve: Sequence[float],
    rebalance_dates: Sequence[date],
) -> list[dict[str, str]]:
    """Strategy + benchmark equity sampled at each rebalance date — the FE chart series (QV-071).
    Compact by design (daily curve → the result artifact, QV-067)."""
    index = {d: i for i, d in enumerate(sessions)}
    out: list[dict[str, str]] = []
    for d in rebalance_dates:
        i = index.get(d)
        if i is not None and i < len(curve) and i < len(bench_curve):
            out.append(
                {"as_of": d.isoformat(), "strategy": _s(curve[i]), "benchmark": _s(bench_curve[i])}
            )
    return out


def empty_metrics() -> dict[str, Any]:
    """A valid, all-zero suite for a degenerate range (fewer than two sessions)."""
    zero = _s(0.0)
    metrics: dict[str, Any] = {k: zero for k in _SCALAR_KEYS}
    metrics["n_rebalances"] = 0
    metrics["exposure_series"] = []
    metrics["equity_curve"] = []
    return metrics


__all__ = ["compute_metrics", "empty_metrics"]

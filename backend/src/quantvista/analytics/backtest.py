"""Backtest engine (QV-065) — the deterministic factor-strategy rebalance loop.

QV-062 shipped the async submit/poll lifecycle with a placeholder; this is the real compute. At each
rebalance date ``D`` the engine reads the **survivorship-free** universe, ranks it **PIT**,
equal-weights the top-``N``, and holds to the next rebalance on **adjusted-close** returns —
modelling transaction costs, slippage, and turnover, and force-exiting delisted names at last price.

Everything is read through the ``BacktestData`` seam (QV-063/064), so the two cardinal sins —
look-ahead and survivorship bias — are *structurally* impossible: no "latest"/unbounded read exists
here. The result keeps ``BacktestResult``'s shape (metrics + ``result_ref``); the **full** metrics
suite is QV-068, the Parquet artifact QV-067, and the permanent bias-regression CI guards QV-066.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import numpy as np

from quantvista.analytics.scoring import MODEL_VERSION  # ranking methodology fingerprint
from quantvista.market_data.trading_calendar import sessions_in_range
from quantvista.schemas.backtest import BacktestSpec

# A fixed slippage assumption (bps), added to the spec's commission on each traded unit of turnover.
SLIPPAGE_BPS = 5
WEIGHTS_VERSION = "equal-weight-v1"
_TRADING_DAYS = 252  # annualisation factor for vol/Sharpe


class BacktestData(Protocol):
    """The PIT read seam the engine consumes (satisfied structurally by ``BacktestDataAccess``)."""

    def universe_as_of(
        self, as_of: date, *, index_code: str = ..., market: str = ...
    ) -> list[UUID]: ...

    def ranked_universe(
        self, as_of: date, universe: Sequence[UUID], *, rank_by: str = ..., top_n: int
    ) -> list[UUID]: ...

    def price_panel(
        self, start: date, end: date, stock_ids: Sequence[UUID]
    ) -> dict[UUID, dict[date, Decimal]]: ...

    def last_price_as_of(
        self, as_of: date, stock_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[date, Decimal]]: ...


@dataclass(frozen=True)
class BacktestResult:
    """Outcome of a backtest run: metrics (Decimal-as-string) + an artifact reference.

    ``result_ref`` is the object-store key for the full result artifact (QV-067); this engine keeps
    the metrics in the row's JSONB and leaves ``result_ref`` ``None``.
    """

    metrics: dict[str, Any] = field(default_factory=dict)
    result_ref: str | None = None


def _bucket(d: date, cadence: str) -> tuple[int, int]:
    """The rebalance bucket a session date falls in (its first session becomes a rebalance date)."""
    if cadence == "weekly":
        iso = d.isocalendar()
        return (iso.year, iso.week)
    if cadence == "quarterly":
        return (d.year, (d.month - 1) // 3)
    return (d.year, d.month)  # monthly (default)


def _rebalance_dates(sessions: Sequence[date], cadence: str) -> list[date]:
    """First session of each cadence bucket within ``sessions`` (ordered)."""
    seen: set[tuple[int, int]] = set()
    out: list[date] = []
    for d in sessions:
        b = _bucket(d, cadence)
        if b not in seen:
            seen.add(b)
            out.append(d)
    return out


def _equal_weight(priced: Sequence[UUID]) -> dict[UUID, float]:
    if not priced:
        return {}
    w = 1.0 / len(priced)
    return {sid: w for sid in priced}


def _turnover(target: dict[UUID, float], held: dict[UUID, float]) -> float:
    names = set(target) | set(held)
    return 0.5 * sum(abs(target.get(n, 0.0) - held.get(n, 0.0)) for n in names)


def _s(x: float) -> str:
    """Serialise a float metric as a Decimal string (never a raw float on the wire)."""
    return str(Decimal(str(round(float(x), 8))))


class BacktestEngine:
    """Runs a validated ``BacktestSpec`` into a ``BacktestResult`` via the ``BacktestData`` seam."""

    def __init__(self, data: BacktestData) -> None:
        self._data = data

    def run(self, spec: BacktestSpec) -> BacktestResult:
        sessions = sessions_in_range(spec.start, spec.end)
        if len(sessions) < 2:
            return BacktestResult(metrics=_empty_metrics(), result_ref=None)

        rebal_dates = _rebalance_dates(sessions, spec.rules.rebalance)
        picks = {
            d: self._data.ranked_universe(
                d,
                self._data.universe_as_of(d, index_code=spec.universe),
                rank_by=spec.rules.rank_by,
                top_n=spec.rules.top_n,
            )
            for d in rebal_dates
        }
        bench_ids = self._data.universe_as_of(sessions[0], index_code=spec.universe)

        all_ids = sorted(
            {sid for ranked in picks.values() for sid in ranked} | set(bench_ids), key=str
        )
        panel = self._data.price_panel(spec.start, spec.end, all_ids)

        cost_rate = (spec.costs_bps + SLIPPAGE_BPS) / 10_000.0
        strat_targets = {
            d: _equal_weight([p for p in picks[d] if panel.get(p, {}).get(d) is not None])
            for d in rebal_dates
        }
        curve, period_returns, turnovers = self._simulate(sessions, panel, strat_targets, cost_rate)

        bench_targets = {
            sessions[0]: _equal_weight([b for b in bench_ids if panel.get(b, {}).get(sessions[0])])
        }
        bench_curve, _, _ = self._simulate(sessions, panel, bench_targets, 0.0)

        metrics = _metrics(
            sessions, curve, period_returns, turnovers, bench_curve, len(rebal_dates)
        )
        metrics["model_version"] = MODEL_VERSION
        metrics["weights_version"] = WEIGHTS_VERSION
        return BacktestResult(metrics=metrics, result_ref=None)

    def _simulate(
        self,
        sessions: Sequence[date],
        panel: dict[UUID, dict[date, Decimal]],
        targets_by_date: dict[date, dict[UUID, float]],
        cost_rate: float,
    ) -> tuple[list[float], list[float], list[float]]:
        """Walk the sessions: realise weighted daily returns, force-exit gaps, rebalance on cadence.

        Returns ``(equity_curve, period_returns, turnovers)``. Cash (unallocated weight) earns 0.
        """
        equity = 1.0
        held: dict[UUID, float] = {}
        curve: list[float] = []
        period_returns: list[float] = []
        turnovers: list[float] = []
        prev: date | None = None

        for cur in sessions:
            if prev is not None:
                step = 0.0
                exits: list[UUID] = []
                for sid, w in held.items():
                    p_prev = panel.get(sid, {}).get(prev)
                    p_cur = panel.get(sid, {}).get(cur)
                    if p_prev is not None and p_cur is not None:
                        step += w * (float(p_cur) / float(p_prev) - 1.0)
                    else:  # a gap ⇒ the name delisted: force-exit at its last valid price (QV-064)
                        self._data.last_price_as_of(cur, [sid])
                        exits.append(sid)  # realised at last price (0 further return), → cash
                equity *= 1.0 + step
                period_returns.append(step)
                for sid in exits:
                    held.pop(sid, None)

            target = targets_by_date.get(cur)
            if target is not None:
                turnover = _turnover(target, held)
                equity *= 1.0 - turnover * cost_rate
                turnovers.append(turnover)
                held = dict(target)

            curve.append(equity)
            prev = cur
        return curve, period_returns, turnovers


def _metrics(
    sessions: Sequence[date],
    curve: Sequence[float],
    period_returns: Sequence[float],
    turnovers: Sequence[float],
    bench_curve: Sequence[float],
    n_rebalances: int,
) -> dict[str, Any]:
    total = curve[-1] - 1.0
    bench = bench_curve[-1] - 1.0
    years = max((sessions[-1] - sessions[0]).days / 365.25, 1e-9)
    cagr = curve[-1] ** (1.0 / years) - 1.0 if curve[-1] > 0 else -1.0
    r = np.asarray(period_returns, dtype=np.float64)
    std = float(r.std(ddof=1)) if r.size > 1 else 0.0
    vol = std * float(np.sqrt(_TRADING_DAYS))
    sharpe = float(r.mean()) / std * float(np.sqrt(_TRADING_DAYS)) if std > 0 else 0.0
    c = np.asarray(curve, dtype=np.float64)
    max_dd = float((c / np.maximum.accumulate(c) - 1.0).min()) if c.size else 0.0
    avg_turnover = float(np.mean(turnovers)) if turnovers else 0.0
    return {
        "total_return": _s(total),
        "cagr": _s(cagr),
        "ann_vol": _s(vol),
        "sharpe": _s(sharpe),
        "max_drawdown": _s(max_dd),
        "avg_turnover": _s(avg_turnover),
        "n_rebalances": n_rebalances,
        "benchmark_return": _s(bench),
        "excess_return": _s(total - bench),
    }


def _empty_metrics() -> dict[str, Any]:
    """A valid, all-zero metrics dict for a degenerate range (fewer than two sessions)."""
    zero = _s(0.0)
    return {
        "total_return": zero,
        "cagr": zero,
        "ann_vol": zero,
        "sharpe": zero,
        "max_drawdown": zero,
        "avg_turnover": zero,
        "n_rebalances": 0,
        "benchmark_return": zero,
        "excess_return": zero,
        "model_version": MODEL_VERSION,
        "weights_version": WEIGHTS_VERSION,
    }


__all__ = ["BacktestData", "BacktestEngine", "BacktestResult", "SLIPPAGE_BPS", "WEIGHTS_VERSION"]

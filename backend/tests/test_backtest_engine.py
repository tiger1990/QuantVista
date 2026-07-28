"""Unit tests for the BacktestEngine rebalance loop (QV-065) — no DB.

The engine depends on a ``BacktestData`` Protocol; here a scripted fake feeds it deterministic
picks/prices so we can pin the loop math exactly: core metrics, determinism, frictions biting,
delisting forced-exit (via ``last_price_as_of``), benchmark, and cadence. The real-seam wiring is
covered by ``tests/integration/test_backtest_engine_run.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from quantvista.analytics.backtest import BacktestEngine, BacktestResult
from quantvista.market_data.trading_calendar import sessions_in_range
from quantvista.schemas.backtest import BacktestSpec

_START = date(2023, 1, 1)
_END = date(2023, 3, 31)
_SESSIONS = sessions_in_range(_START, _END)  # real NSE calendar (deterministic)
_IDS = [uuid4() for _ in range(4)]  # a fixed 4-name universe


def _spec(*, costs_bps: int = 0, rebalance: str = "monthly", top_n: int = 2) -> BacktestSpec:
    return BacktestSpec.model_validate(
        {
            "rules": {"rank_by": "composite", "top_n": top_n, "rebalance": rebalance},
            "start": _START.isoformat(),
            "end": _END.isoformat(),
            "costs_bps": costs_bps,
        }
    )


class FakeData:
    """Scripted ``BacktestData``: a fixed ranking, a linear price path, optional delisting."""

    def __init__(self, *, step: float = 1.0, delist: UUID | None = None, delist_after: int = 20):
        self.step = step
        self.delist = delist
        self.delist_date = _SESSIONS[delist_after] if delist else None
        self.last_price_calls: list[UUID] = []  # spy for the forced-exit assertion

    def _alive(self, on: date) -> list[UUID]:
        if self.delist and self.delist_date and on >= self.delist_date:
            return [s for s in _IDS if s != self.delist]
        return list(_IDS)

    def universe_as_of(
        self, as_of: date, *, index_code: str = "NIFTY200", market: str = "NSE"
    ) -> list[UUID]:
        return self._alive(as_of)

    def ranked_universe(
        self, as_of: date, universe: Sequence[UUID], *, rank_by: str = "composite", top_n: int
    ) -> list[UUID]:
        return [s for s in _IDS if s in set(universe)][:top_n]  # fixed ranking, respect membership

    def price_panel(
        self, start: date, end: date, stock_ids: Sequence[UUID]
    ) -> dict[UUID, dict[date, Decimal]]:
        panel: dict[UUID, dict[date, Decimal]] = {}
        for i, sid in enumerate(_IDS):
            if sid not in set(stock_ids):
                continue
            series: dict[date, Decimal] = {}
            for k, d in enumerate(_SESSIONS):
                if (
                    self.delist
                    and sid == self.delist
                    and self.delist_date
                    and d >= self.delist_date
                ):
                    break  # no bars after delisting
                series[d] = Decimal(str(100 + i + k * self.step))
            panel[sid] = series
        return panel

    def last_price_as_of(
        self, as_of: date, stock_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[date, Decimal]]:
        out: dict[UUID, tuple[date, Decimal]] = {}
        for i, sid in enumerate(_IDS):
            if sid not in set(stock_ids):
                continue
            self.last_price_calls.append(sid)
            bars = [
                (d, Decimal(str(100 + i + k * self.step)))
                for k, d in enumerate(_SESSIONS)
                if d <= as_of
                and not (
                    self.delist
                    and sid == self.delist
                    and self.delist_date
                    and d >= self.delist_date
                )
            ]
            if bars:
                out[sid] = bars[-1]
        return out


_METRIC_KEYS = {
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


def test_engine_produces_typed_core_metrics() -> None:
    result = BacktestEngine(FakeData()).run(_spec())
    assert isinstance(result, BacktestResult)
    assert set(result.metrics) >= _METRIC_KEYS
    # Scalar metrics are Decimal strings; n_rebalances is an int; exposure_series is a list.
    for k in _METRIC_KEYS - {"n_rebalances", "exposure_series"}:
        assert isinstance(result.metrics[k], str)
    assert result.metrics["n_rebalances"] == 3  # Jan/Feb/Mar monthly buckets
    assert isinstance(result.metrics["exposure_series"], list)
    assert result.result_ref is None  # artifact offload is QV-067


def test_determinism_same_spec_same_metrics() -> None:
    a = BacktestEngine(FakeData()).run(_spec())
    b = BacktestEngine(FakeData()).run(_spec())
    assert a.metrics == b.metrics


def test_frictions_reduce_return() -> None:
    free = BacktestEngine(FakeData()).run(_spec(costs_bps=0))
    costly = BacktestEngine(FakeData()).run(_spec(costs_bps=100))
    assert Decimal(costly.metrics["total_return"]) < Decimal(free.metrics["total_return"])
    assert Decimal(free.metrics["avg_turnover"]) > 0  # turnover exists, so costs must bite


def test_cadence_changes_rebalance_count() -> None:
    weekly = BacktestEngine(FakeData()).run(_spec(rebalance="weekly"))
    monthly = BacktestEngine(FakeData()).run(_spec(rebalance="monthly"))
    quarterly = BacktestEngine(FakeData()).run(_spec(rebalance="quarterly"))
    assert (
        weekly.metrics["n_rebalances"]
        > monthly.metrics["n_rebalances"]
        > quarterly.metrics["n_rebalances"]
    )


def test_degenerate_range_returns_zeroed_metrics() -> None:
    # A range with fewer than two trading sessions (a weekend) → a valid all-zero result, no crash.
    spec = BacktestSpec.model_validate(
        {
            "rules": {"top_n": 2},
            "start": "2023-01-07",  # Saturday
            "end": "2023-01-08",  # Sunday → no sessions in between
        }
    )
    m = BacktestEngine(FakeData()).run(spec).metrics
    assert m["n_rebalances"] == 0
    assert Decimal(m["total_return"]) == Decimal("0")


def test_benchmark_and_excess_consistent() -> None:
    m = BacktestEngine(FakeData()).run(_spec()).metrics
    excess = Decimal(m["total_return"]) - Decimal(m["benchmark_return"])
    assert abs(excess - Decimal(m["excess_return"])) < Decimal("0.0000001")


def test_delisting_forces_exit_at_last_price() -> None:
    victim = _IDS[0]  # top-ranked, so it's held from rebalance 1
    data = FakeData(delist=victim, delist_after=20)
    result = BacktestEngine(data).run(_spec(top_n=2))
    # The run completes with finite metrics and the delisted name was priced for a forced exit.
    assert set(result.metrics) >= _METRIC_KEYS
    assert victim in data.last_price_calls  # AC-4: exit valued via last_price_as_of


def test_flat_prices_only_lose_to_costs() -> None:
    # Flat prices → zero gross return; the only drag is friction. Slippage applies even at zero
    # commission (AC-3: cost = turnover·(costs_bps+SLIPPAGE_BPS)/1e4), so both runs end below 1.0.
    free = BacktestEngine(FakeData(step=0.0)).run(_spec(costs_bps=0))
    costly = BacktestEngine(FakeData(step=0.0)).run(_spec(costs_bps=100))
    assert Decimal(free.metrics["total_return"]) < Decimal("0")  # slippage always bites
    assert Decimal(costly.metrics["total_return"]) < Decimal(free.metrics["total_return"])

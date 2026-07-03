"""Data-quality gates over real Postgres (QV-018) — fake bus, seeded throwaway universe.

Seeds a small universe (unique index_code) + daily_prices, then drives each gate: a clean run
passes and emits PricesValidated; a broken run trips the matching gate, emits DataQualityGateFailed,
and (via the task) fails the jobs_runs row. The service commits nothing here (read-only), so the
fixture just cleans up the rows it seeded.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs.quality import DataQualityGateError, validate_prices
from quantvista.market_data.quality import QualityThresholds
from quantvista.market_data.services import DataQualityService

pytestmark = pytest.mark.integration

# Three consecutive NSE sessions (Mon–Wed, 2026-06-01..03) so gap math has a real window.
D1, D2, D3 = date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object]]] = []

    def publish(self, topic: str, event: dict[str, object]) -> None:
        self.published.append((topic, event))

    def subscribe(self, topic: str, handler: object) -> None: ...

    def topics(self) -> set[str]:
        return {t for t, _ in self.published}


@dataclass
class _Universe:
    index_code: str
    market: str
    ids: list[UUID]


def _price(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "open": Decimal("100"),
        "high": Decimal("105"),
        "low": Decimal("99"),
        "close": Decimal("102"),
        "volume": 1000,
    }
    row.update(overrides)
    return row


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[_Universe]:
    """Two stocks (AAA, BBB), each with a clean bar on D1/D2/D3, under a unique index_code."""
    market_id, index_code = uuid4(), f"TESTDQ_{uuid4().hex[:8]}"
    aaa, bbb = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        for sid, sym in [(aaa, "AAA"), (bbb, "BBB")]:
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name) "
                    "VALUES (:id, :m, :s, 'Co')"
                ),
                {"id": sid, "m": market_id, "s": sym},
            )
            conn.execute(
                text(
                    "INSERT INTO index_constituents (id, index_code, stock_id, effective_from) "
                    "VALUES (gen_random_uuid(), :ic, :s, '2020-01-01')"
                ),
                {"ic": index_code, "s": sid},
            )
            for on in (D1, D2, D3):
                conn.execute(
                    text(
                        "INSERT INTO daily_prices "
                        "(stock_id, date, open, high, low, close, adj_close, volume, source) "
                        "VALUES (:s, :d, :open, :high, :low, :close, :close, :volume, 'seed')"
                    ),
                    {"s": sid, "d": on, **_price()},
                )
    with admin_engine.connect() as conn:
        market = str(
            conn.execute(
                text("SELECT code FROM markets WHERE id = :m"), {"m": market_id}
            ).scalar_one()
        )
    yield _Universe(index_code, market, [aaa, bbb])
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:i)"), {"i": [aaa, bbb]})
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code = :ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": [aaa, bbb]})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def _validate(u: _Universe, bus: _FakeBus, thresholds: QualityThresholds | None = None):  # type: ignore[no-untyped-def]
    return DataQualityService(bus).validate(
        u.market, D1, D3, index_code=u.index_code, thresholds=thresholds
    )


def test_clean_universe_passes_and_emits_prices_validated(
    admin_engine: Engine, universe: _Universe
) -> None:
    bus = _FakeBus()
    report = _validate(universe, bus)
    assert report.passed and report.violations == []
    assert report.stocks_validated == 2 and report.expected_stocks == 2
    assert bus.topics() == {"PricesValidated"}


def test_missing_stock_trips_coverage_gate(admin_engine: Engine, universe: _Universe) -> None:
    # Drop every row for BBB → only 1/2 stocks have data → coverage 0.5 < 0.95
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = :s"), {"s": universe.ids[1]})
    bus = _FakeBus()
    report = _validate(universe, bus)
    assert not report.passed
    assert {v.gate for v in report.violations} == {"coverage", "gap"}
    assert "BBB" in report.violations[0].detail
    assert bus.topics() == {"DataQualityGateFailed"}


def test_null_cells_trip_null_rate_gate(admin_engine: Engine, universe: _Universe) -> None:
    # NULL out close on 3 of 6 rows → null_rate = 3/30 = 0.10 > 0.01. Coverage/gap stay clean.
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE daily_prices SET close = NULL WHERE stock_id = :s"), {"s": universe.ids[0]}
        )
    bus = _FakeBus()
    report = _validate(universe, bus)
    assert not report.passed
    assert "null_rate" in {v.gate for v in report.violations}
    assert bus.topics() == {"DataQualityGateFailed"}


def test_nonpositive_and_bound_violations_trip_price_sanity(
    admin_engine: Engine, universe: _Universe
) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE daily_prices SET close = 0 WHERE stock_id = :s AND date = :d"),
            {"s": universe.ids[0], "d": D1},
        )
        # high < low → OHLC-bound violation
        conn.execute(
            text("UPDATE daily_prices SET high = 1, low = 500 WHERE stock_id = :s AND date = :d"),
            {"s": universe.ids[1], "d": D2},
        )
    bus = _FakeBus()
    report = _validate(universe, bus)
    assert not report.passed
    sanity = next(v for v in report.violations if v.gate == "price_sanity")
    # Both categories present. (The close=0 row is *also* an OHLC-bound violation via low>close,
    # so the bound count is 2 — a real overlap, not a bug.)
    assert "non-positive" in sanity.detail and "OHLC-bound" in sanity.detail
    assert bus.topics() == {"DataQualityGateFailed"}


def test_missing_session_trips_gap_gate(admin_engine: Engine, universe: _Universe) -> None:
    # Remove the mid-window session for BOTH stocks → 2 missing of 6 slots = 0.33 > 0.02,
    # but both stocks still have data (D1/D3) so coverage stays clean → isolates the gap gate.
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE date = :d"), {"d": D2})
    bus = _FakeBus()
    report = _validate(universe, bus)
    assert not report.passed
    assert {v.gate for v in report.violations} == {"gap"}


def test_loose_thresholds_allow_a_marginal_run(admin_engine: Engine, universe: _Universe) -> None:
    # Same missing-session data, but a backfill-style loose gap threshold lets it pass.
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE date = :d"), {"d": D2})
    bus = _FakeBus()
    report = _validate(universe, bus, QualityThresholds(max_missing_session_rate=Decimal("0.50")))
    assert report.passed and bus.topics() == {"PricesValidated"}


def test_task_fails_run_when_gate_trips(admin_engine: Engine, universe: _Universe) -> None:
    # A single-date validate for D2; delete BBB's D2 row → coverage 0.5 → task raises + run failed.
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM daily_prices WHERE stock_id = :s AND date = :d"),
            {"s": universe.ids[1], "d": D2},
        )
    # The task validates its own market; point it at our seeded universe's market via NIFTY200?
    # The task hard-codes NIFTY200, so drive the failure through the range helper instead, which
    # accepts index_code — exercising the same _run_validate + run_job + strict-raise path.
    from quantvista.jobs.quality import validate_prices_range

    key_market = universe.market
    with pytest.raises(DataQualityGateError):
        validate_prices_range(key_market, start=D2, end=D2, index_code=universe.index_code)
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"),
            {"k": f"dq:prices:{key_market}:backfill:{D2.isoformat()}:{D2.isoformat()}"},
        ).scalar_one()
    assert status == "failed"
    # cleanup the jobs_runs row
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "dq:prices:%"})


def test_task_succeeds_on_clean_single_date(admin_engine: Engine, universe: _Universe) -> None:
    from quantvista.jobs.quality import validate_prices_range

    outcome = validate_prices_range(
        universe.market, start=D1, end=D1, index_code=universe.index_code
    )
    assert outcome.status.value == "succeeded"
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "dq:prices:%"})


# Keep the daily-task symbol imported (task wiring smoke — construction only, no network).
def test_daily_task_is_registered() -> None:
    assert validate_prices.name == "quantvista.validate_prices"

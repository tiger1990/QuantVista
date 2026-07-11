"""ingest_fundamentals (QV-022) — fake provider, real Postgres; versioned upsert + corrections.

Wires the QV-021 bitemporal primitive over the universe. Proves: filings insert +
FundamentalsUpdated, idempotent re-run, restatement → revised, period_end=None skipped, per-stock
isolation, and the task under run_job. Throwaway universe under a unique index_code, cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.jobs import ingest as ingest_mod
from quantvista.jobs.framework import run_key
from quantvista.jobs.ingest import IngestRunFailed, _run_fundamentals, ingest_fundamentals
from quantvista.market_data.fundamentals import fundamentals_as_of
from quantvista.market_data.models import (
    CorporateAction,
    FundamentalSnapshot,
    LicenseClass,
    PriceBar,
    Provenance,
    ShareholdingSnapshot,
    UniverseEntry,
)
from quantvista.market_data.services import FundamentalsIngestionService

pytestmark = pytest.mark.integration

_PROV = Provenance("yfinance", None, LicenseClass.NON_COMMERCIAL_DEV)
_PERIOD = date(2025, 12, 31)
T0 = datetime(2026, 1, 15, tzinfo=UTC)
T1 = datetime(2026, 2, 10, tzinfo=UTC)


def _snap(symbol: str, *, pe: str | None, period_end: date | None = _PERIOD) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        period_end=period_end,
        statement_type="quarterly",
        pe=Decimal(pe) if pe is not None else None,
        forward_pe=None,
        pb=None,
        roe=None,
        roce=None,
        debt_equity=None,
        provenance=_PROV,
    )


def _snap_full(symbol: str, period_end: date) -> FundamentalSnapshot:
    """A QV-095-shaped dated snapshot carrying the widened ratio set (intrinsic + valuation)."""
    return FundamentalSnapshot(
        symbol=symbol,
        period_end=period_end,
        statement_type="annual",
        pe=Decimal("20"),
        forward_pe=None,
        pb=Decimal("3"),
        roe=Decimal("0.15"),
        roce=Decimal("0.18"),
        debt_equity=Decimal("0.5"),
        provenance=_PROV,
        roic=Decimal("0.12"),
        revenue=Decimal("1000"),
        net_margin=Decimal("0.12"),
        eps=Decimal("1.2"),
    )


class _FakeProvider:
    def __init__(
        self, funds: dict[str, list[FundamentalSnapshot]], raise_for: set[str] | None = None
    ) -> None:
        self._funds = funds
        self._raise = raise_for or set()

    def get_fundamentals(self, symbol: str) -> Sequence[FundamentalSnapshot]:
        if symbol in self._raise:
            raise RuntimeError(f"provider boom for {symbol}")
        return self._funds.get(symbol, [])

    def get_prices(
        self, symbol: str, start: date, end: date, interval: str = "1d"
    ) -> Sequence[PriceBar]:
        return []

    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        return []

    def get_shareholding(self, symbol: str) -> Sequence[ShareholdingSnapshot]:
        return []

    def list_universe(self, index_code: str = "NIFTY200") -> Sequence[UniverseEntry]:
        return []


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
    aaa: UUID
    bbb: UUID


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[_Universe]:
    market_id, index_code = uuid4(), f"TESTFUND_{uuid4().hex[:8]}"
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
    market = "NSE"
    with admin_engine.connect() as conn:
        market = str(
            conn.execute(
                text("SELECT code FROM markets WHERE id = :m"), {"m": market_id}
            ).scalar_one()
        )
    yield _Universe(index_code, market, aaa, bbb)
    with admin_engine.begin() as conn:
        ids = [aaa, bbb]
        conn.execute(text("DELETE FROM fundamentals WHERE stock_id = ANY(:i)"), {"i": ids})
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code = :ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "fund:%"})


def _row_count(admin_engine: Engine, stock_id: UUID) -> int:
    with admin_engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM fundamentals WHERE stock_id = :s"), {"s": stock_id}
            ).scalar_one()
        )


def test_insert_emits_event_and_is_readable_as_of(
    admin_engine: Engine, universe: _Universe
) -> None:
    provider = _FakeProvider({"AAA": [_snap("AAA", pe="10")]})
    bus = _FakeBus()
    report = FundamentalsIngestionService(provider, bus).ingest(
        universe.market, index_code=universe.index_code, knowledge_time=T0
    )
    assert report.filings_inserted == 1 and report.stocks_ok == 1
    assert bus.topics() == {"FundamentalsUpdated"}
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        v = fundamentals_as_of(session, universe.aaa, T1)
    assert v is not None and v.ratios["pe"] == Decimal("10.000000")


def test_reingest_is_idempotent(admin_engine: Engine, universe: _Universe) -> None:
    svc = FundamentalsIngestionService(_FakeProvider({"AAA": [_snap("AAA", pe="10")]}), _FakeBus())
    svc.ingest(universe.market, index_code=universe.index_code, knowledge_time=T0)
    again = svc.ingest(universe.market, index_code=universe.index_code, knowledge_time=T1)
    assert again.filings_unchanged == 1 and again.filings_inserted == 0
    assert _row_count(admin_engine, universe.aaa) == 1  # no new version


def test_restatement_creates_a_revision(admin_engine: Engine, universe: _Universe) -> None:
    FundamentalsIngestionService(
        _FakeProvider({"AAA": [_snap("AAA", pe="10")]}), _FakeBus()
    ).ingest(universe.market, index_code=universe.index_code, knowledge_time=T0)
    report = FundamentalsIngestionService(
        _FakeProvider({"AAA": [_snap("AAA", pe="12")]}), _FakeBus()
    ).ingest(universe.market, index_code=universe.index_code, knowledge_time=T1)
    assert report.filings_revised == 1
    assert _row_count(admin_engine, universe.aaa) == 2  # old closed + new open
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        v = fundamentals_as_of(session, universe.aaa, T1)
    assert v is not None and v.ratios["pe"] == Decimal("12.000000")


def test_period_end_none_is_skipped(admin_engine: Engine, universe: _Universe) -> None:
    provider = _FakeProvider({"AAA": [_snap("AAA", pe="10", period_end=None)]})
    report = FundamentalsIngestionService(provider, _FakeBus()).ingest(
        universe.market, index_code=universe.index_code, knowledge_time=T0
    )
    # AAA's only snapshot has no period_end (a ttm rolling metric, not a filing) → skipped; BBB has
    # nothing. Both stocks count as no-data, and no fundamentals row is written.
    assert report.filings_inserted == 0 and report.stocks_no_data == 2
    assert _row_count(admin_engine, universe.aaa) == 0


def test_per_stock_failure_is_isolated(admin_engine: Engine, universe: _Universe) -> None:
    provider = _FakeProvider({"AAA": [_snap("AAA", pe="10")]}, raise_for={"BBB"})
    report = FundamentalsIngestionService(provider, _FakeBus()).ingest(
        universe.market, index_code=universe.index_code, knowledge_time=T0
    )
    assert report.stocks_failed == 1 and report.failures[0][0] == "BBB"
    assert report.filings_inserted == 1  # AAA still ingested


class _FakeYf:
    _raise = False

    def get_fundamentals(self, symbol: str) -> Sequence[FundamentalSnapshot]:
        if _FakeYf._raise:
            raise RuntimeError(f"down for {symbol}")
        return [_snap(symbol, pe="10")]


def test_task_succeeds_and_records(
    admin_engine: Engine, universe: _Universe, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeYf._raise = False
    monkeypatch.setattr(ingest_mod, "YFinanceDevProvider", _FakeYf)
    # The task hard-codes NIFTY200; drive our throwaway universe by pointing the seed at it is not
    # possible, so exercise the run_job path via the internal runner with our index_code.
    key = run_key("fund", universe.market, "test", uuid4().hex[:8])
    outcome = _run_fundamentals(universe.market, key, universe.index_code)
    assert outcome.status.value == "succeeded"
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"), {"k": key}
        ).scalar_one()
    assert status == "succeeded"


def test_task_strict_fail_marks_run_failed(
    admin_engine: Engine, universe: _Universe, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeYf._raise = True
    monkeypatch.setattr(ingest_mod, "YFinanceDevProvider", _FakeYf)
    key = run_key("fund", universe.market, "fail", uuid4().hex[:8])
    with pytest.raises(IngestRunFailed):
        _run_fundamentals(universe.market, key, universe.index_code)
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"), {"k": key}
        ).scalar_one()
    assert status == "failed"
    _FakeYf._raise = False


def test_dated_multi_period_versions_and_widened_ratios(
    admin_engine: Engine, universe: _Universe
) -> None:
    # QV-095: the adapter now returns one dated snapshot PER fiscal period (not a single TTM stub).
    # Each distinct period_end must become its own bitemporal row, and the widened ratio set
    # (roic/net_margin/revenue/eps …) must persist and read back — not just the original 6.
    p0, p1 = date(2026, 3, 31), date(2025, 3, 31)
    provider = _FakeProvider({"AAA": [_snap_full("AAA", p0), _snap_full("AAA", p1)]})
    report = FundamentalsIngestionService(provider, _FakeBus()).ingest(
        universe.market, index_code=universe.index_code, knowledge_time=T0
    )
    assert report.filings_inserted == 2  # one row per fiscal period
    assert _row_count(admin_engine, universe.aaa) == 2
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        latest = fundamentals_as_of(session, universe.aaa, T1, statement_type="annual")
    assert latest is not None
    assert latest.ratios["roic"] == Decimal("0.120000")  # widened intrinsic ratio round-trips
    assert latest.ratios["net_margin"] == Decimal("0.120000")
    assert latest.ratios["pe"] == Decimal("20.000000")


def test_daily_task_is_registered() -> None:
    assert ingest_fundamentals.name == "quantvista.ingest_fundamentals"

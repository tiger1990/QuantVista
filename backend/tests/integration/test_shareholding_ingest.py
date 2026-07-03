"""ingest_shareholding (QV-023) — fake provider, real Postgres; PIT-by-date upsert.

Shareholding is keyed (stock_id, as_of_date): re-polling a date updates in place, a new quarter is
a new row. No event (06 catalog emits —). Throwaway universe under a unique index_code, cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs import ingest as ingest_mod
from quantvista.jobs.framework import run_key
from quantvista.jobs.ingest import IngestRunFailed, _run_shareholding, ingest_shareholding
from quantvista.market_data.models import (
    CorporateAction,
    FundamentalSnapshot,
    LicenseClass,
    PriceBar,
    Provenance,
    ShareholdingSnapshot,
    UniverseEntry,
)
from quantvista.market_data.services import ShareholdingIngestionService

pytestmark = pytest.mark.integration

_PROV = Provenance("yfinance", None, LicenseClass.NON_COMMERCIAL_DEV)
Q1, Q2 = date(2025, 9, 30), date(2025, 12, 31)


def _snap(symbol: str, *, promoter: str, as_of: date = Q1) -> ShareholdingSnapshot:
    return ShareholdingSnapshot(
        symbol=symbol,
        as_of_date=as_of,
        promoter_holding=Decimal(promoter),
        fii_holding=None,
        dii_holding=None,
        public_holding=None,
        pledged_pct=None,
        provenance=_PROV,
    )


class _FakeProvider:
    def __init__(
        self, hold: dict[str, list[ShareholdingSnapshot]], raise_for: set[str] | None = None
    ) -> None:
        self._hold = hold
        self._raise = raise_for or set()

    def get_shareholding(self, symbol: str) -> Sequence[ShareholdingSnapshot]:
        if symbol in self._raise:
            raise RuntimeError(f"provider boom for {symbol}")
        return self._hold.get(symbol, [])

    def get_prices(
        self, symbol: str, start: date, end: date, interval: str = "1d"
    ) -> Sequence[PriceBar]:
        return []

    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        return []

    def get_fundamentals(self, symbol: str) -> Sequence[FundamentalSnapshot]:
        return []

    def list_universe(self, index_code: str = "NIFTY200") -> Sequence[UniverseEntry]:
        return []


@dataclass
class _Universe:
    index_code: str
    market: str
    aaa: UUID
    bbb: UUID


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[_Universe]:
    market_id, index_code = uuid4(), f"TESTSHP_{uuid4().hex[:8]}"
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
    with admin_engine.connect() as conn:
        market = str(
            conn.execute(
                text("SELECT code FROM markets WHERE id = :m"), {"m": market_id}
            ).scalar_one()
        )
    yield _Universe(index_code, market, aaa, bbb)
    with admin_engine.begin() as conn:
        ids = [aaa, bbb]
        conn.execute(text("DELETE FROM shareholding WHERE stock_id = ANY(:i)"), {"i": ids})
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code = :ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "shp:%"})


def _rows(admin_engine: Engine, stock_id: UUID) -> list[tuple[date, Decimal]]:
    with admin_engine.connect() as conn:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT as_of_date, promoter_holding FROM shareholding "
                    "WHERE stock_id = :s ORDER BY as_of_date"
                ),
                {"s": stock_id},
            )
        ]


def test_insert_records_holding(admin_engine: Engine, universe: _Universe) -> None:
    provider = _FakeProvider({"AAA": [_snap("AAA", promoter="50")]})
    report = ShareholdingIngestionService(provider).ingest(
        universe.market, index_code=universe.index_code
    )
    assert report.rows_upserted == 1 and report.stocks_ok == 1
    assert _rows(admin_engine, universe.aaa) == [(Q1, Decimal("50.0000"))]


def test_same_date_upsert_is_idempotent(admin_engine: Engine, universe: _Universe) -> None:
    ShareholdingIngestionService(_FakeProvider({"AAA": [_snap("AAA", promoter="50")]})).ingest(
        universe.market, index_code=universe.index_code
    )
    # Re-poll the SAME quarter with a corrected value → updated in place, still one row.
    ShareholdingIngestionService(_FakeProvider({"AAA": [_snap("AAA", promoter="55")]})).ingest(
        universe.market, index_code=universe.index_code
    )
    assert _rows(admin_engine, universe.aaa) == [(Q1, Decimal("55.0000"))]


def test_new_quarter_is_a_new_row(admin_engine: Engine, universe: _Universe) -> None:
    ShareholdingIngestionService(_FakeProvider({"AAA": [_snap("AAA", promoter="50")]})).ingest(
        universe.market, index_code=universe.index_code
    )
    ShareholdingIngestionService(
        _FakeProvider({"AAA": [_snap("AAA", promoter="48", as_of=Q2)]})
    ).ingest(universe.market, index_code=universe.index_code)
    assert _rows(admin_engine, universe.aaa) == [
        (Q1, Decimal("50.0000")),
        (Q2, Decimal("48.0000")),
    ]


def test_empty_result_is_no_data(admin_engine: Engine, universe: _Universe) -> None:
    report = ShareholdingIngestionService(_FakeProvider({})).ingest(
        universe.market, index_code=universe.index_code
    )
    assert report.rows_upserted == 0 and report.stocks_no_data == 2
    assert _rows(admin_engine, universe.aaa) == []


def test_per_stock_failure_is_isolated(admin_engine: Engine, universe: _Universe) -> None:
    provider = _FakeProvider({"AAA": [_snap("AAA", promoter="50")]}, raise_for={"BBB"})
    report = ShareholdingIngestionService(provider).ingest(
        universe.market, index_code=universe.index_code
    )
    assert report.stocks_failed == 1 and report.failures[0][0] == "BBB"
    assert report.rows_upserted == 1  # AAA still ingested


class _FakeYf:
    _raise = False

    def get_shareholding(self, symbol: str) -> Sequence[ShareholdingSnapshot]:
        if _FakeYf._raise:
            raise RuntimeError(f"down for {symbol}")
        return [_snap(symbol, promoter="50")]


def test_task_succeeds_and_records(
    admin_engine: Engine, universe: _Universe, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeYf._raise = False
    monkeypatch.setattr(ingest_mod, "YFinanceDevProvider", _FakeYf)
    key = run_key("shp", universe.market, "test", uuid4().hex[:8])
    outcome = _run_shareholding(universe.market, key, universe.index_code)
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
    key = run_key("shp", universe.market, "fail", uuid4().hex[:8])
    with pytest.raises(IngestRunFailed):
        _run_shareholding(universe.market, key, universe.index_code)
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"), {"k": key}
        ).scalar_one()
    assert status == "failed"
    _FakeYf._raise = False


def test_daily_task_is_registered() -> None:
    assert ingest_shareholding.name == "quantvista.ingest_shareholding"

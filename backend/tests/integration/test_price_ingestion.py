"""End-to-end daily-price ingestion (QV-016) — fake provider/bus, real Postgres.

Isolates the universe by seeding a throwaway market + stocks + open constituents under a
**unique** index_code (so ``active_universe`` returns only our test stocks, not the seeded
NIFTY200). The service commits real rows, so the fixture cleans up afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.market_data.models import (
    CorporateAction,
    FundamentalSnapshot,
    LicenseClass,
    PriceBar,
    Provenance,
    ShareholdingSnapshot,
    UniverseEntry,
)
from quantvista.market_data.services import PriceIngestionService

pytestmark = pytest.mark.integration

_PROV = Provenance("yfinance", None, LicenseClass.NON_COMMERCIAL_DEV)


def _bar(symbol: str, on: date, close: str) -> PriceBar:
    c = Decimal(close)
    return PriceBar(symbol, on, Decimal("100"), Decimal("101"), Decimal("99"), c, c, 1000, _PROV)


class _FakeProvider:
    def __init__(self, bars: dict[str, list[PriceBar]], raise_for: set[str] | None = None) -> None:
        self._bars = bars
        self._raise = raise_for or set()

    def get_prices(
        self, symbol: str, start: date, end: date, interval: str = "1d"
    ) -> Sequence[PriceBar]:
        if symbol in self._raise:
            raise RuntimeError(f"provider boom for {symbol}")
        return self._bars.get(symbol, [])

    # Remaining IMarketDataProvider surface — unused by ingestion, stubbed for the protocol.
    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        return []

    def get_fundamentals(self, symbol: str) -> Sequence[FundamentalSnapshot]:
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


@dataclass
class _Universe:
    index_code: str
    market: str
    stocks: list[tuple[UUID, str]]  # (stock_id, symbol)


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[_Universe]:
    market_code = f"T{uuid4().hex[:6]}"
    index_code = f"TESTIDX_{uuid4().hex[:8]}"
    market_id = uuid4()
    stocks = [(uuid4(), "AAA"), (uuid4(), "BBB")]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :code, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "code": market_code},
        )
        for sid, sym in stocks:
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name) "
                    "VALUES (:id, :m, :sym, 'Test Co')"
                ),
                {"id": sid, "m": market_id, "sym": sym},
            )
            conn.execute(
                text(
                    "INSERT INTO index_constituents (id, index_code, stock_id, effective_from) "
                    "VALUES (gen_random_uuid(), :ic, :s, '2020-01-01')"
                ),
                {"ic": index_code, "s": sid},
            )
    yield _Universe(index_code, market_code, stocks)
    with admin_engine.begin() as conn:
        ids = [sid for sid, _ in stocks]
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:ids)"), {"ids": ids})
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code = :ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:ids)"), {"ids": ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def _price_row(admin_engine: Engine, stock_id: UUID, on: date) -> tuple[Decimal, Decimal] | None:
    with admin_engine.connect() as conn:
        row = conn.execute(
            text("SELECT close, adj_close FROM daily_prices WHERE stock_id = :s AND date = :d"),
            {"s": stock_id, "d": on},
        ).one_or_none()
    return (row[0], row[1]) if row else None


def test_ingest_upserts_all_stocks(admin_engine: Engine, universe: _Universe) -> None:
    # Arrange
    on = date(2026, 6, 30)
    provider = _FakeProvider(
        {"AAA": [_bar("AAA", on, "2940.55")], "BBB": [_bar("BBB", on, "1500.00")]}
    )
    svc = PriceIngestionService(provider, _FakeBus())
    # Act
    report = svc.ingest(universe.market, on, on, index_code=universe.index_code)
    # Assert
    assert (report.stocks_ok, report.stocks_failed, report.rows_upserted) == (2, 0, 2)
    (sid_a, _), (sid_b, _) = universe.stocks
    assert _price_row(admin_engine, sid_a, on) == (Decimal("2940.55"), Decimal("2940.55"))
    assert _price_row(admin_engine, sid_b, on) is not None


def test_reingest_is_idempotent_and_updates(admin_engine: Engine, universe: _Universe) -> None:
    # Arrange
    on = date(2026, 6, 30)

    def svc(close: str) -> PriceIngestionService:
        bars = {"AAA": [_bar("AAA", on, close)], "BBB": [_bar("BBB", on, "1")]}
        return PriceIngestionService(_FakeProvider(bars), _FakeBus())

    svc("2940.55").ingest(universe.market, on, on, index_code=universe.index_code)
    # Act — re-run with a changed close for AAA
    svc("3000.00").ingest(universe.market, on, on, index_code=universe.index_code)
    # Assert — still one row per stock (upsert), value refreshed
    sid_a = universe.stocks[0][0]
    with admin_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM daily_prices WHERE stock_id = :s"), {"s": sid_a}
        ).scalar_one()
    assert count == 1
    assert _price_row(admin_engine, sid_a, on) == (Decimal("3000.00"), Decimal("3000.00"))


def test_per_stock_failure_isolated(admin_engine: Engine, universe: _Universe) -> None:
    # Arrange — BBB's provider call raises; AAA succeeds
    on = date(2026, 6, 30)
    provider = _FakeProvider({"AAA": [_bar("AAA", on, "100")]}, raise_for={"BBB"})
    report = PriceIngestionService(provider, _FakeBus()).ingest(
        universe.market, on, on, index_code=universe.index_code
    )
    # Assert — AAA upserted, BBB recorded as a failure, run continued
    assert report.stocks_ok == 1 and report.stocks_failed == 1
    assert report.failures[0][0] == "BBB"
    assert _price_row(admin_engine, universe.stocks[0][0], on) is not None


def test_no_data_is_not_a_failure(admin_engine: Engine, universe: _Universe) -> None:
    # Arrange — provider returns [] for both (e.g. holiday)
    on = date(2026, 6, 30)
    report = PriceIngestionService(_FakeProvider({}), _FakeBus()).ingest(
        universe.market, on, on, index_code=universe.index_code
    )
    # Assert — counted as no-data, NOT failures
    assert (report.stocks_no_data, report.stocks_failed, report.rows_upserted) == (2, 0, 0)


def test_pricesingested_event_emitted(admin_engine: Engine, universe: _Universe) -> None:
    # Arrange
    on = date(2026, 6, 30)
    bus = _FakeBus()
    PriceIngestionService(_FakeProvider({"AAA": [_bar("AAA", on, "100")]}), bus).ingest(
        universe.market, on, on, index_code=universe.index_code
    )
    # Assert
    topic, event = bus.published[0]
    assert topic == "PricesIngested"
    assert event["market"] == universe.market and event["stocks_ok"] == 1

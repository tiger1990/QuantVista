"""Corporate-action ingestion + adjusted-close (QV-017) — fake provider, real Postgres.

Seeds a throwaway universe (unique index_code) with two stocks and raw daily_prices, then
drives the split/bonus back-adjustment and idempotency. The service commits, so the fixture
cleans up. Dividends must NOT move adj_close (03 §5).
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
    CorporateActionType,
    FundamentalSnapshot,
    LicenseClass,
    PriceBar,
    Provenance,
    ShareholdingSnapshot,
    UniverseEntry,
)
from quantvista.market_data.services import CorporateActionIngestionService

pytestmark = pytest.mark.integration

_PROV = Provenance("yfinance", None, LicenseClass.NON_COMMERCIAL_DEV)
D1, D2, D3 = date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)


def _action(sym: str, ex: date, kind: CorporateActionType, ratio: str) -> CorporateAction:
    return CorporateAction(sym, ex, kind, Decimal(ratio), {}, _PROV)


class _FakeProvider:
    def __init__(
        self, actions: dict[str, list[CorporateAction]], raise_for: set[str] | None = None
    ) -> None:
        self._actions = actions
        self._raise = raise_for or set()

    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        if symbol in self._raise:
            raise RuntimeError(f"provider boom for {symbol}")
        return self._actions.get(symbol, [])

    def get_prices(
        self, symbol: str, start: date, end: date, interval: str = "1d"
    ) -> Sequence[PriceBar]:
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
    aaa: UUID
    bbb: UUID


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[_Universe]:
    market_id, index_code = uuid4(), f"TESTIDX_{uuid4().hex[:8]}"
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
        # AAA raw closes: 100, 100, 50 (a 2:1 split on D3). adj_close starts = close.
        for on, close in [(D1, "100"), (D2, "100"), (D3, "50")]:
            conn.execute(
                text(
                    "INSERT INTO daily_prices (stock_id, date, close, adj_close, source) "
                    "VALUES (:s, :d, :c, :c, 'seed')"
                ),
                {"s": aaa, "d": on, "c": Decimal(close)},
            )
    yield _Universe(index_code, "NSE", aaa, bbb)  # market code set on the row above via :c
    with admin_engine.begin() as conn:
        ids = [aaa, bbb]
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:i)"), {"i": ids})
        conn.execute(text("DELETE FROM corporate_actions WHERE stock_id = ANY(:i)"), {"i": ids})
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code = :ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def _market(admin_engine: Engine, u: _Universe) -> str:
    with admin_engine.connect() as conn:
        return str(
            conn.execute(
                text(
                    "SELECT m.code FROM markets m JOIN stocks s ON s.market_id=m.id WHERE s.id=:s"
                ),
                {"s": u.aaa},
            ).scalar_one()
        )


def _adj(admin_engine: Engine, stock_id: UUID) -> dict[date, Decimal]:
    with admin_engine.connect() as conn:
        return {
            r[0]: r[1]
            for r in conn.execute(
                text("SELECT date, adj_close FROM daily_prices WHERE stock_id=:s"), {"s": stock_id}
            )
        }


def test_split_back_adjusts_prior_closes(admin_engine: Engine, universe: _Universe) -> None:
    # Arrange — a 2:1 split on D3; provider returns it for AAA
    market = _market(admin_engine, universe)
    provider = _FakeProvider({"AAA": [_action("AAA", D3, CorporateActionType.SPLIT, "2")]})
    report = CorporateActionIngestionService(provider, _FakeBus()).ingest(
        market, D1, D3, index_code=universe.index_code
    )
    # Assert — pre-split closes halved (100→50), the ex-date close (50) unchanged
    adj = _adj(admin_engine, universe.aaa)
    assert adj[D1] == Decimal("50.0000")
    assert adj[D2] == Decimal("50.0000")
    assert adj[D3] == Decimal("50.0000")
    assert report.actions_upserted == 1 and report.stocks_adjusted >= 1


def test_recompute_is_idempotent(admin_engine: Engine, universe: _Universe) -> None:
    market = _market(admin_engine, universe)
    svc = CorporateActionIngestionService(
        _FakeProvider({"AAA": [_action("AAA", D3, CorporateActionType.SPLIT, "2")]}), _FakeBus()
    )
    svc.ingest(market, D1, D3, index_code=universe.index_code)
    svc.ingest(market, D1, D3, index_code=universe.index_code)  # re-run
    adj = _adj(admin_engine, universe.aaa)
    assert adj[D1] == Decimal("50.0000")  # not double-adjusted
    with admin_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM corporate_actions WHERE stock_id=:s"), {"s": universe.aaa}
        ).scalar_one()
    assert n == 1  # upsert, no duplicate


def test_dividend_does_not_move_adj_close(admin_engine: Engine, universe: _Universe) -> None:
    market = _market(admin_engine, universe)
    provider = _FakeProvider({"AAA": [_action("AAA", D2, CorporateActionType.DIVIDEND, "5")]})
    CorporateActionIngestionService(provider, _FakeBus()).ingest(
        market, D1, D3, index_code=universe.index_code
    )
    # adj_close stays equal to raw close — dividends are stored, not applied (03 §5)
    adj = _adj(admin_engine, universe.aaa)
    assert adj[D1] == Decimal("100.0000") and adj[D3] == Decimal("50.0000")


def test_late_split_readjusts_history(admin_engine: Engine, universe: _Universe) -> None:
    market = _market(admin_engine, universe)
    bus = _FakeBus()
    # First: no actions → adj_close == close
    CorporateActionIngestionService(_FakeProvider({}), bus).ingest(
        market, D1, D3, index_code=universe.index_code
    )
    assert _adj(admin_engine, universe.aaa)[D1] == Decimal("100.0000")
    # Later: a split arrives → recompute re-adjusts the history
    CorporateActionIngestionService(
        _FakeProvider({"AAA": [_action("AAA", D3, CorporateActionType.SPLIT, "2")]}), bus
    ).ingest(market, D1, D3, index_code=universe.index_code)
    assert _adj(admin_engine, universe.aaa)[D1] == Decimal("50.0000")


def test_per_stock_failure_isolated_and_event_emitted(
    admin_engine: Engine, universe: _Universe
) -> None:
    market = _market(admin_engine, universe)
    bus = _FakeBus()
    provider = _FakeProvider(
        {"AAA": [_action("AAA", D3, CorporateActionType.SPLIT, "2")]}, raise_for={"BBB"}
    )
    report = CorporateActionIngestionService(provider, bus).ingest(
        market, D1, D3, index_code=universe.index_code
    )
    # AAA processed, BBB isolated as a failure; CorpActionsUpdated emitted
    assert report.stocks_failed == 1 and report.failures[0][0] == "BBB"
    assert _adj(admin_engine, universe.aaa)[D1] == Decimal("50.0000")
    assert bus.published[0][0] == "CorpActionsUpdated"

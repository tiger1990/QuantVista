"""Backtest engine data reader (QV-065) — real Postgres.

The rebalance-loop math is unit-tested against a scripted seam in ``tests/test_backtest_engine.py``;
the full real-seam + job wiring is exercised by ``test_api_backtests.py``. This file covers the one
piece of **new DB code** — the per-name adjusted-close price panel the engine walks — on real PG:
PIT-bounded, non-intersecting (a delisted name keeps its own short series). Rolled-back, no residue.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.backtest import BacktestData
from quantvista.analytics.backtest_data import BacktestDataAccess
from quantvista.market_data.repositories import adjusted_close_panel

pytestmark = pytest.mark.integration

_START = date(2024, 1, 1)
_END = date(2024, 1, 10)


@pytest.fixture
def seeded(admin_engine: Engine) -> Iterator[tuple[Session, UUID, UUID]]:
    """Two stocks: ``full`` priced across the window, ``delisted`` with bars only to 2024-01-05."""
    with admin_engine.connect() as conn:
        trans = conn.begin()
        try:
            market_id = uuid4()
            conn.execute(
                text(
                    "INSERT INTO markets (id, code, name, country, currency, timezone) "
                    "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
                ),
                {"id": market_id, "c": f"BT{uuid4().hex[:6]}"},
            )
            full, delisted = uuid4(), uuid4()
            for sid in (full, delisted):
                conn.execute(
                    text(
                        "INSERT INTO stocks (id, market_id, symbol, company_name) "
                        "VALUES (:id, :m, :sym, 'Co')"
                    ),
                    {"id": sid, "m": market_id, "sym": f"BT{uuid4().hex[:6]}"},
                )
            _seed_prices(conn, full, _START, _END, base=100)  # full window
            _seed_prices(conn, delisted, _START, date(2024, 1, 5), base=200)  # delists mid-window
            with Session(bind=conn) as session:
                yield session, full, delisted
        finally:
            trans.rollback()


def _seed_prices(conn: Connection, sid: UUID, start: date, end: date, *, base: int) -> None:
    rows, d, i = [], start, 0
    while d <= end:
        px = Decimal(str(base + i))
        rows.append({"s": sid, "d": d, "c": px})
        d, i = d + timedelta(days=1), i + 1
    conn.execute(
        text(
            "INSERT INTO daily_prices "
            "(stock_id, date, close, adj_close, high, low, volume, source) "
            "VALUES (:s, :d, :c, :c, :c, :c, 100, 'seed')"
        ),
        rows,
    )


def test_panel_returns_per_name_series(seeded: tuple[Session, UUID, UUID]) -> None:
    session, full, delisted = seeded
    panel = adjusted_close_panel(session, [full, delisted], _START, _END)
    assert set(panel) == {full, delisted}
    assert panel[full][_START] == Decimal("100")
    assert max(panel[full]) == _END  # full name spans the whole window


def test_panel_is_non_intersecting_for_delisted(seeded: tuple[Session, UUID, UUID]) -> None:
    session, full, delisted = seeded
    panel = adjusted_close_panel(session, [full, delisted], _START, _END)
    # The delisted name keeps its own short series; it does NOT trim the full name's coverage.
    assert max(panel[delisted]) == date(2024, 1, 5)
    assert max(panel[full]) == _END


def test_panel_is_pit_bounded(seeded: tuple[Session, UUID, UUID]) -> None:
    session, full, _ = seeded
    panel = adjusted_close_panel(session, [full], _START, date(2024, 1, 4))
    assert max(panel[full]) == date(2024, 1, 4)  # nothing past `end` leaks in


def test_panel_empty_ids(seeded: tuple[Session, UUID, UUID]) -> None:
    session, _, _ = seeded
    assert adjusted_close_panel(session, [], _START, _END) == {}


def test_seam_price_panel_delegates(seeded: tuple[Session, UUID, UUID]) -> None:
    session, full, delisted = seeded
    data = BacktestDataAccess(session)
    panel = data.price_panel(_START, _END, [full, delisted])
    assert panel[full][_START] == Decimal("100")


def test_backtest_data_access_satisfies_protocol(seeded: tuple[Session, UUID, UUID]) -> None:
    session, _, _ = seeded
    data: BacktestData = BacktestDataAccess(session)  # structural typing check (engine's seam)
    assert callable(data.universe_as_of) and callable(data.price_panel)

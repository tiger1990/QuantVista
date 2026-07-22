"""Integration tests for the bulk PIT readers (market_data.repositories, QV-058).

`latest_closes` / `latest_betas` back the RiskEngine: one query for N holdings (not N+1), and
point-in-time — a bar/indicator dated after ``as_of`` must be invisible (project rule #4). Seeds a
market + stocks + ``daily_prices`` + ``technical_indicators`` via the admin engine (global tables,
no RLS), mirroring ``test_returns_matrix.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.market_data.repositories import latest_betas, latest_closes

pytestmark = pytest.mark.integration

_D1 = date(2025, 3, 1)
_AS_OF = date(2025, 3, 2)
_FUTURE = date(2025, 3, 3)


@pytest.fixture
def seeded(admin_engine: Engine) -> Iterator[dict[str, UUID]]:
    market_id = uuid4()
    a, b, c = uuid4(), uuid4(), uuid4()  # a: full; b: NULL beta; c: no TI row
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'T', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        for sid in (a, b, c):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name) "
                    "VALUES (:id, :m, :s, 'Co')"
                ),
                {"id": sid, "m": market_id, "s": f"BLK{uuid4().hex[:6]}"},
            )
        # daily_prices: a has d1/as_of/future; the future close (999) must be invisible at as_of.
        price_rows = [
            {"s": a, "d": _D1, "c": Decimal("100")},
            {"s": a, "d": _AS_OF, "c": Decimal("110")},
            {"s": a, "d": _FUTURE, "c": Decimal("999")},
            {"s": b, "d": _AS_OF, "c": Decimal("50")},
        ]
        conn.execute(
            text(
                "INSERT INTO daily_prices (stock_id, date, open, high, low, close, adj_close, "
                "volume, source) VALUES (:s, :d, :c, :c, :c, :c, :c, 1000, 'seed')"
            ),
            price_rows,
        )
        # technical_indicators: a has beta d1/as_of/future; b's latest beta is NULL; c has no row.
        ti_rows = [
            {"s": a, "d": _D1, "beta": Decimal("1.0")},
            {"s": a, "d": _AS_OF, "beta": Decimal("1.2")},
            {"s": a, "d": _FUTURE, "beta": Decimal("9.0")},
            {"s": b, "d": _AS_OF, "beta": None},
        ]
        conn.execute(
            text(
                "INSERT INTO technical_indicators (stock_id, date, beta_1y) VALUES (:s, :d, :beta)"
            ),
            ti_rows,
        )
    yield {"a": a, "b": b, "c": c}
    with admin_engine.begin() as conn:
        ids = [a, b, c]
        conn.execute(text("DELETE FROM technical_indicators WHERE stock_id = ANY(:i)"), {"i": ids})
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:i)"), {"i": ids})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def test_latest_closes_is_point_in_time(seeded: dict[str, UUID], admin_engine: Engine) -> None:
    ids = [seeded["a"], seeded["b"], seeded["c"]]
    with Session(admin_engine) as session:
        closes = latest_closes(session, ids, _AS_OF)
    assert closes[seeded["a"]] == Decimal("110")  # the as_of bar, NOT the future 999
    assert closes[seeded["b"]] == Decimal("50")
    assert seeded["c"] not in closes  # no price → omitted


def test_latest_betas_pit_null_and_missing(seeded: dict[str, UUID], admin_engine: Engine) -> None:
    ids = [seeded["a"], seeded["b"], seeded["c"]]
    with Session(admin_engine) as session:
        betas = latest_betas(session, ids, _AS_OF)
    assert betas[seeded["a"]] == Decimal("1.2")  # as_of row, not the future 9.0
    assert betas[seeded["b"]] is None  # present row, NULL beta_1y
    assert seeded["c"] not in betas  # no indicator row → omitted


def test_bulk_readers_empty_input(admin_engine: Engine) -> None:
    with Session(admin_engine) as session:
        assert latest_closes(session, [], _AS_OF) == {}
        assert latest_betas(session, [], _AS_OF) == {}

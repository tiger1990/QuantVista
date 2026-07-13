"""Integration tests for the PIT returns-matrix reader (market_data.returns, QV-054).

Exercises the three things the optimizer relies on: point-in-time bounding (a bar dated after
``as_of`` is invisible — no look-ahead, project rule #4), alignment on common dates, and dropping
+ reporting names with insufficient history. Seeds a market + stocks + ``daily_prices`` via the
admin engine (global tables, no RLS), mirroring ``test_compute_indicators.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.market_data.returns import returns_matrix_as_of

pytestmark = pytest.mark.integration

_START = date(2024, 1, 1)


@pytest.fixture
def priced_universe(admin_engine: Engine) -> Iterator[dict[str, UUID]]:
    market_id = uuid4()
    good_a, good_b, thin = uuid4(), uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'T', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        rows = []
        for sid, base, n_days in [(good_a, 100.0, 6), (good_b, 50.0, 6), (thin, 25.0, 1)]:
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name) "
                    "VALUES (:id, :m, :s, 'Co')"
                ),
                {"id": sid, "m": market_id, "s": f"S{uuid4().hex[:5]}"},
            )
            for i in range(n_days):  # consecutive daily bars D0..D{n-1}
                p = base * (1.0 + 0.01 * i)
                rows.append(
                    {"s": sid, "d": _START + timedelta(days=i), "c": Decimal(str(round(p, 4)))}
                )
        # A future-dated bar for good_a AFTER our as_of — must be excluded by the PIT filter.
        rows.append({"s": good_a, "d": _START + timedelta(days=30), "c": Decimal("999.0")})
        conn.execute(
            text(
                "INSERT INTO daily_prices "
                "(stock_id, date, close, adj_close, high, low, volume, source) "
                "VALUES (:s, :d, :c, :c, :c, :c, 1000, 'seed')"
            ),
            rows,
        )
    yield {"market_id": market_id, "good_a": good_a, "good_b": good_b, "thin": thin}
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM daily_prices WHERE stock_id = ANY(:i)"),
            {"i": [good_a, good_b, thin]},
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": [good_a, good_b, thin]})
        conn.execute(text("DELETE FROM markets WHERE id=:m"), {"m": market_id})


def test_returns_matrix_aligns_survivors_and_drops_thin(
    admin_engine: Engine, priced_universe: dict[str, UUID]
) -> None:
    good_a = priced_universe["good_a"]
    good_b = priced_universe["good_b"]
    thin = priced_universe["thin"]
    as_of = _START + timedelta(days=5)  # D5 — the last seeded in-window bar
    with Session(admin_engine) as session:
        rm = returns_matrix_as_of(session, [good_a, good_b, thin], as_of, min_observations=2)
    # thin (1 price) dropped + reported; good_a/good_b survive
    assert set(rm.stock_ids) == {good_a, good_b}
    assert rm.dropped == (thin,)
    # 6 in-window prices (D0..D5) → 5 returns; future D30 bar excluded by PIT
    assert rm.values.shape == (5, 2)
    assert len(rm.dates) == 5
    assert max(rm.dates) == as_of  # nothing dated after as_of


def test_pit_excludes_future_bar(admin_engine: Engine, priced_universe: dict[str, UUID]) -> None:
    good_a = priced_universe["good_a"]
    good_b = priced_universe["good_b"]
    # as_of BEFORE the last in-window bar → only D0..D3 visible → 3 returns
    as_of = _START + timedelta(days=3)
    with Session(admin_engine) as session:
        rm = returns_matrix_as_of(session, [good_a, good_b], as_of, min_observations=2)
    assert rm.values.shape == (3, 2)
    assert max(rm.dates) == as_of


def test_returns_are_simple_pct_change(
    admin_engine: Engine, priced_universe: dict[str, UUID]
) -> None:
    good_a = priced_universe["good_a"]
    as_of = _START + timedelta(days=5)
    with Session(admin_engine) as session:
        rm = returns_matrix_as_of(session, [good_a], as_of, min_observations=2)
    # seeded as base*(1+0.01*i): each step return ≈ 0.01/(1+0.01*i)
    assert rm.values.shape == (5, 1)
    assert rm.values[0, 0] == pytest.approx(0.01 / 1.00, rel=1e-6)
    assert rm.values[1, 0] == pytest.approx(0.01 / 1.01, rel=1e-6)


def test_lookback_window_limits_history(
    admin_engine: Engine, priced_universe: dict[str, UUID]
) -> None:
    good_a = priced_universe["good_a"]
    good_b = priced_universe["good_b"]
    as_of = _START + timedelta(days=5)
    # lookback of 2 days → only D3, D4, D5 in window → 2 returns
    with Session(admin_engine) as session:
        rm = returns_matrix_as_of(
            session, [good_a, good_b], as_of, lookback_days=2, min_observations=2
        )
    assert rm.values.shape == (2, 2)
    assert min(rm.dates) >= as_of - timedelta(days=2)


def test_all_insufficient_returns_empty(
    admin_engine: Engine, priced_universe: dict[str, UUID]
) -> None:
    thin = priced_universe["thin"]
    missing = uuid4()  # never seeded
    as_of = _START + timedelta(days=5)
    with Session(admin_engine) as session:
        rm = returns_matrix_as_of(session, [thin, missing], as_of, min_observations=2)
    assert rm.stock_ids == ()
    assert set(rm.dropped) == {thin, missing}
    assert rm.values.shape == (0, 0)

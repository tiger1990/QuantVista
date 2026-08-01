"""Derived-data coverage metric (QV-105) — real PostgreSQL.

Freshness could not have caught the bug this measures. When `technical_indicators` covered 18
sessions behind 286 of prices, ``max(date)`` was **identical** for both: the freshness gauge read
perfectly healthy while a year of backtests silently returned zeros. These tests pin that the
coverage gauge sees what freshness cannot.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.jobs.ops_metrics import update_coverage_gap
from quantvista.market_data.repositories import derived_coverage_gap, latest_price_date

pytestmark = pytest.mark.integration

_TODAY = date.today()
_DAYS = [_TODAY - timedelta(days=n) for n in range(10)]


@pytest.fixture
def priced_stock(admin_engine: Engine) -> Iterator[UUID]:
    """One stock priced on 10 recent days, with indicators on only the most recent."""
    market_id, stock_id = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'COV', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"COV{uuid4().hex[:5]}"},
        )
        conn.execute(
            text(
                "INSERT INTO stocks (id, market_id, symbol, company_name) "
                "VALUES (:id, :m, :sym, 'Co')"
            ),
            {"id": stock_id, "m": market_id, "sym": f"COV{uuid4().hex[:5]}"},
        )
        conn.execute(
            text(
                "INSERT INTO daily_prices (stock_id, date, close, adj_close, source) "
                "VALUES (:s, :d, 1, 1, 'cov')"
            ),
            [{"s": stock_id, "d": d} for d in _DAYS],
        )
        # indicators for the NEWEST day only — same max(date) as prices, almost no coverage
        conn.execute(
            text("INSERT INTO technical_indicators (stock_id, date, ret_6m) VALUES (:s, :d, 1)"),
            {"s": stock_id, "d": _DAYS[0]},
        )
    yield stock_id
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM technical_indicators WHERE stock_id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM stocks WHERE id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def test_freshness_looks_healthy_while_coverage_is_missing(
    admin_engine: Engine, priced_stock: UUID
) -> None:
    """THE POINT OF THIS METRIC: identical max(date), yet history is absent.

    The gauge is deliberately **global** (a system-wide health signal), so this asserts the
    relationship rather than an exact count — other stocks in a shared database legitimately
    contribute coverage on some of the same dates.
    """
    with Session(admin_engine) as session:
        newest_price = latest_price_date(session)
        newest_indicator = session.execute(
            text("SELECT max(date) FROM technical_indicators")
        ).scalar_one()
        gap = derived_coverage_gap(session, "technical_indicators", since=_DAYS[-1])

    assert newest_price == newest_indicator, "freshness would report both datasets equally current"
    assert gap > 0, "…while the coverage gauge sees history that freshness cannot"


def test_gap_shrinks_as_the_history_is_filled(admin_engine: Engine, priced_stock: UUID) -> None:
    """Filling the seeded stock's missing dates must strictly reduce the measured gap."""
    with Session(admin_engine) as session:
        before = derived_coverage_gap(session, "technical_indicators", since=_DAYS[-1])
    assert before > 0

    with admin_engine.begin() as conn:  # simulate the backfill landing
        conn.execute(
            text("INSERT INTO technical_indicators (stock_id, date, ret_6m) VALUES (:s, :d, 1)"),
            [{"s": priced_stock, "d": d} for d in _DAYS[1:]],
        )

    with Session(admin_engine) as session:
        after = derived_coverage_gap(session, "technical_indicators", since=_DAYS[-1])
    assert after < before, "filling the missing sessions must close the gap they caused"


def test_unknown_dataset_is_rejected_not_interpolated() -> None:
    """The query concatenates the table name, so the allow-list is a security boundary."""
    with (
        pytest.raises(ValueError, match="unknown derived dataset"),
        Session(_engine()) as session,
    ):
        derived_coverage_gap(session, "daily_prices; DROP TABLE stocks", since=_TODAY)


def _engine() -> Engine:
    from quantvista.core.db import app_engine

    return app_engine()


def test_update_publishes_a_gauge_per_derived_dataset(
    admin_engine: Engine, priced_stock: UUID
) -> None:
    from quantvista.core.observability.metrics import DATA_COVERAGE_GAP

    with Session(admin_engine) as session:
        gaps = update_coverage_gap(session, lookback_days=30)

    assert set(gaps) == {"technical_indicators", "factor_values", "scores"}
    published = DATA_COVERAGE_GAP.labels(dataset="technical_indicators")._value.get()
    assert published == gaps["technical_indicators"]

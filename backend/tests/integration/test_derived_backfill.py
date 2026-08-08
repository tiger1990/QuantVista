"""Range backfill for derived data (QV-105) — real PostgreSQL.

The bug: prices had a range backfill since QV-016, but indicators/factors/scores were computed for a
*single* date. A database could therefore hold a year of prices behind one day of indicators, and a
backtest over that range would silently hold nothing — 0.00% on every strategy metric while the
benchmark, which is pure price maths, looked healthy. Nothing raised.

These tests pin that the derived steps now span the window, and that the coverage gap which caused
it is detectable rather than silent.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs.compute import backfill_indicators
from quantvista.market_data.trading_calendar import sessions_in_range

pytestmark = pytest.mark.integration

# A short, fixed window in the past: enough sessions to prove the loop, cheap enough to run in CI.
_START = date(2026, 3, 2)
_END = date(2026, 3, 6)
# Unique per run. A hardcoded market code is a unique key in a SHARED database: if teardown is ever
# skipped — an interrupted run, an error before the fixture yields — the row survives and every
# later run dies on `duplicate key value violates unique constraint "markets_code_key"`. Every other
# fixture in this suite already suffixes with a uuid; this one did not, and it bit exactly that way.
_RUN_ID = uuid4().hex[:6].upper()
_MARKET = f"QV105{_RUN_ID}"
_INDEX = f"QV105IDX{_RUN_ID}"


@pytest.fixture
def seeded_universe(admin_engine: Engine) -> Iterator[list[UUID]]:
    """A tiny isolated market with priced stocks in the window, so the compute has real input."""
    market_id, stock_ids = uuid4(), [uuid4() for _ in range(3)]
    sessions = sessions_in_range(_START, _END)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'QV105', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": _MARKET},
        )
        for i, sid in enumerate(stock_ids):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :sym, 'Co', 'IT')"
                ),
                {"id": sid, "m": market_id, "sym": f"QV105{i}"},
            )
            conn.execute(
                text(
                    "INSERT INTO index_constituents (index_code, stock_id, effective_from, weight) "
                    "VALUES (:idx, :s, :d, 1)"
                ),
                {"idx": _INDEX, "s": sid, "d": date(2026, 1, 1)},
            )
        # a longer price history than the window: indicators need lookback to produce values
        conn.execute(
            text(
                "INSERT INTO daily_prices (stock_id, date, close, adj_close, source) "
                "VALUES (:s, :d, :p, :p, 'qv105')"
            ),
            [
                {"s": sid, "d": d, "p": 100 + i + k}
                for i, sid in enumerate(stock_ids)
                for k, d in enumerate(sessions_in_range(date(2025, 9, 1), _END))
            ],
        )
    assert sessions  # guards the fixture itself: an empty window would make the tests vacuous
    yield stock_ids
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM technical_indicators WHERE stock_id = ANY(:ids)"), {"ids": stock_ids}
        )
        conn.execute(
            text("DELETE FROM daily_prices WHERE stock_id = ANY(:ids)"), {"ids": stock_ids}
        )
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code = :idx"), {"idx": _INDEX}
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:ids)"), {"ids": stock_ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})
        # The ledger must go too. Deleting the rows but leaving `jobs_runs` makes the next test's
        # backfill a no-op ("already succeeded") and it fails for a reason that has nothing to do
        # with the code under test — which is exactly how this suite first misled me.
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :p"), {"p": f"ind:{_MARKET}:%"})


def _indicator_dates(engine: Engine, stock_ids: list[UUID]) -> set[date]:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text("SELECT DISTINCT date FROM technical_indicators WHERE stock_id = ANY(:ids)"),
                {"ids": stock_ids},
            )
        }


def test_backfill_covers_every_session_not_just_the_last(
    admin_engine: Engine, seeded_universe: list[UUID]
) -> None:
    """THE REGRESSION: one date of indicators behind a range of prices is what broke backtests."""
    expected = set(sessions_in_range(_START, _END))
    assert len(expected) > 1, "the window must span several sessions or this proves nothing"

    outcomes = backfill_indicators(_MARKET, start=_START, end=_END, index_code=_INDEX)

    assert len(outcomes) == len(expected)
    assert _indicator_dates(admin_engine, seeded_universe) == expected


def test_backfill_is_idempotent(admin_engine: Engine, seeded_universe: list[UUID]) -> None:
    """Re-running must not duplicate or fail — a partial backfill has to resume cleanly."""
    backfill_indicators(_MARKET, start=_START, end=_END, index_code=_INDEX)
    first = _indicator_dates(admin_engine, seeded_universe)

    backfill_indicators(_MARKET, start=_START, end=_END, index_code=_INDEX)

    assert _indicator_dates(admin_engine, seeded_universe) == first


def test_a_partial_backfill_can_be_completed(
    admin_engine: Engine, seeded_universe: list[UUID]
) -> None:
    """The realistic recovery: someone backfilled a short window, then extends it."""
    sessions = sessions_in_range(_START, _END)
    backfill_indicators(_MARKET, start=sessions[-1], end=sessions[-1], index_code=_INDEX)
    assert _indicator_dates(admin_engine, seeded_universe) == {sessions[-1]}

    backfill_indicators(_MARKET, start=_START, end=_END, index_code=_INDEX)

    assert _indicator_dates(admin_engine, seeded_universe) == set(sessions)


def test_a_date_that_already_ran_is_skipped_without_force(
    admin_engine: Engine, seeded_universe: list[UUID]
) -> None:
    """The ledger's sharp edge, pinned: a date recorded as done is not revisited.

    This matters operationally — a date whose first run wrote partial data (fewer stocks priced
    then than now) stays partial forever unless the caller asks for a repair.
    """
    backfill_indicators(_MARKET, start=_START, end=_END, index_code=_INDEX)
    with admin_engine.begin() as conn:  # simulate a partial/incorrect earlier result
        conn.execute(
            text("DELETE FROM technical_indicators WHERE stock_id = ANY(:ids)"),
            {"ids": seeded_universe},
        )

    again = backfill_indicators(_MARKET, start=_START, end=_END, index_code=_INDEX)

    assert all(o.status.value == "skipped" for o in again)
    assert _indicator_dates(admin_engine, seeded_universe) == set(), "skipped runs write nothing"


def test_force_repairs_a_date_the_ledger_considers_done(
    admin_engine: Engine, seeded_universe: list[UUID]
) -> None:
    """`force=True` is the repair path for exactly the situation above."""
    backfill_indicators(_MARKET, start=_START, end=_END, index_code=_INDEX)
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM technical_indicators WHERE stock_id = ANY(:ids)"),
            {"ids": seeded_universe},
        )

    repaired = backfill_indicators(_MARKET, start=_START, end=_END, index_code=_INDEX, force=True)

    assert all(o.status.value == "succeeded" for o in repaired)
    assert _indicator_dates(admin_engine, seeded_universe) == set(sessions_in_range(_START, _END))

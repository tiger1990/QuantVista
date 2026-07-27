"""Survivorship-free historical universe (QV-064) — real Postgres.

Proves ``historical_universe`` / ``BacktestDataAccess.universe_as_of`` resolve index membership *as
of* ``D`` from the ``index_constituents`` effective-range table, **including names later delisted**
— the cardinal-sin guard (``05`` §4.2). Membership is half-open ``[effective_from, effective_to)``.
Also covers the forced-exit price primitive ``last_adjusted_close_as_of``. Reference tables are
global/no-RLS; all writes run inside a rolled-back transaction (no residue).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.backtest_data import BacktestDataAccess
from quantvista.market_data.repositories import (
    historical_universe,
    last_adjusted_close_as_of,
)

pytestmark = pytest.mark.integration

D = date(2022, 6, 1)  # the rebalance date under test


@dataclass(frozen=True)
class Seed:
    conn: Connection
    session: Session
    index_code: str
    market_code: str
    open_member: UUID  # from < D, to = NULL, active            -> in at D
    dropped_after: UUID  # from < D, to > D, delisted+inactive  -> in at D (survivorship-free)
    dropped_before: UUID  # from < D, to <= D                   -> out at D
    not_yet: UUID  # from > D                                   -> out at D
    boundary_to: UUID  # to == D                                -> out at D (half-open)
    boundary_from: UUID  # from == D, to = NULL                 -> in at D


def _stock(conn: Connection, market_id: UUID, *, delisted_on: date | None, active: bool) -> UUID:
    sid = uuid4()
    conn.execute(
        text(
            "INSERT INTO stocks (id, market_id, symbol, company_name, delisted_on, is_active) "
            "VALUES (:id, :m, :sym, 'Test Co', :d, :active)"
        ),
        {
            "id": sid,
            "m": market_id,
            "sym": f"BT{uuid4().hex[:8]}",
            "d": delisted_on,
            "active": active,
        },
    )
    return sid


def _member(conn: Connection, index_code: str, sid: UUID, ef: date, et: date | None) -> None:
    conn.execute(
        text(
            "INSERT INTO index_constituents "
            "(id, index_code, stock_id, effective_from, effective_to, weight) "
            "VALUES (gen_random_uuid(), :ic, :s, :ef, :et, 0.5)"
        ),
        {"ic": index_code, "s": sid, "ef": ef, "et": et},
    )


@pytest.fixture
def seed(admin_engine: Engine) -> Iterator[Seed]:
    with admin_engine.connect() as conn:
        trans = conn.begin()
        try:
            market_id = uuid4()
            market_code = f"BT{uuid4().hex[:6]}"
            index_code = f"BTX{uuid4().hex[:6]}"
            conn.execute(
                text(
                    "INSERT INTO markets (id, code, name, country, currency, timezone) "
                    "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
                ),
                {"id": market_id, "c": market_code},
            )
            open_member = _stock(conn, market_id, delisted_on=None, active=True)
            dropped_after = _stock(conn, market_id, delisted_on=date(2023, 1, 1), active=False)
            dropped_before = _stock(conn, market_id, delisted_on=None, active=True)
            not_yet = _stock(conn, market_id, delisted_on=None, active=True)
            boundary_to = _stock(conn, market_id, delisted_on=None, active=True)
            boundary_from = _stock(conn, market_id, delisted_on=None, active=True)

            _member(conn, index_code, open_member, date(2021, 1, 1), None)
            _member(conn, index_code, dropped_after, date(2021, 1, 1), date(2023, 1, 1))
            _member(conn, index_code, dropped_before, date(2020, 1, 1), date(2022, 1, 1))
            _member(conn, index_code, not_yet, date(2023, 1, 1), None)
            _member(conn, index_code, boundary_to, date(2021, 1, 1), D)
            _member(conn, index_code, boundary_from, D, None)

            # Adjusted-close bars for the delisted name: last valid bar 2022-12-30.
            for d, adj in ((date(2022, 12, 28), "90"), (date(2022, 12, 30), "95")):
                conn.execute(
                    text(
                        "INSERT INTO daily_prices "
                        "(stock_id, date, open, high, low, close, adj_close, volume, source) "
                        "VALUES (:s, :d, :p, :p, :p, :p, :p, 100, 'seed')"
                    ),
                    {"s": dropped_after, "d": d, "p": Decimal(adj)},
                )

            with Session(bind=conn) as session:
                yield Seed(
                    conn=conn,
                    session=session,
                    index_code=index_code,
                    market_code=market_code,
                    open_member=open_member,
                    dropped_after=dropped_after,
                    dropped_before=dropped_before,
                    not_yet=not_yet,
                    boundary_to=boundary_to,
                    boundary_from=boundary_from,
                )
        finally:
            trans.rollback()


# --- AC-1/AC-2/AC-5: survivorship-free as-of membership ----------------------


def test_universe_at_d_is_survivorship_free(seed: Seed) -> None:
    got = set(historical_universe(seed.session, seed.index_code, seed.market_code, D))
    assert got == {seed.open_member, seed.dropped_after, seed.boundary_from}
    # The load-bearing case: a delisted (is_active=false), later-dropped name IS a member at D.
    assert seed.dropped_after in got
    # Excluded: dropped-before-D, not-yet-member, and the to==D boundary (half-open).
    assert seed.dropped_before not in got
    assert seed.not_yet not in got
    assert seed.boundary_to not in got


def test_delisted_name_drops_out_once_dropped(seed: Seed) -> None:
    # At as_of == effective_to (2023-01-01), the dropped name is no longer a member.
    got = set(
        historical_universe(seed.session, seed.index_code, seed.market_code, date(2023, 1, 1))
    )
    assert seed.dropped_after not in got
    assert seed.open_member in got  # still open


def test_active_universe_would_be_biased(seed: Seed) -> None:
    # Contrast: the survivorship-free read at D includes the later-delisted name, proving the
    # as-of read differs from a "current members only" view.
    at_d = set(historical_universe(seed.session, seed.index_code, seed.market_code, D))
    later = set(
        historical_universe(seed.session, seed.index_code, seed.market_code, date(2024, 1, 1))
    )
    assert seed.dropped_after in at_d and seed.dropped_after not in later


def test_deterministic_order(seed: Seed) -> None:
    a = historical_universe(seed.session, seed.index_code, seed.market_code, D)
    b = historical_universe(seed.session, seed.index_code, seed.market_code, D)
    assert a == b  # stable ordering, repeatable


# --- AC-3: surfaced on the single backtest seam ------------------------------


def test_seam_universe_as_of_matches_repo(seed: Seed) -> None:
    data = BacktestDataAccess(seed.session)
    via_seam = set(data.universe_as_of(D, index_code=seed.index_code, market=seed.market_code))
    assert via_seam == {seed.open_member, seed.dropped_after, seed.boundary_from}


# --- AC-4: forced-exit last-valid-price primitive ----------------------------


def test_last_adjusted_close_returns_last_bar_on_or_before(seed: Seed) -> None:
    got = last_adjusted_close_as_of(seed.session, [seed.dropped_after], date(2023, 6, 1))
    assert got[seed.dropped_after] == (date(2022, 12, 30), Decimal("95"))


def test_last_adjusted_close_respects_as_of(seed: Seed) -> None:
    got = last_adjusted_close_as_of(seed.session, [seed.dropped_after], date(2022, 12, 29))
    assert got[seed.dropped_after] == (date(2022, 12, 28), Decimal("90"))  # 12-30 bar not yet known


def test_last_adjusted_close_absent_when_no_bar(seed: Seed) -> None:
    got = last_adjusted_close_as_of(seed.session, [seed.open_member], date(2023, 6, 1))
    assert seed.open_member not in got  # no bars seeded -> absent (engine handles)


def test_seam_last_price_as_of(seed: Seed) -> None:
    data = BacktestDataAccess(seed.session)
    got = data.last_price_as_of(date(2023, 6, 1), [seed.dropped_after])
    assert got[seed.dropped_after] == (date(2022, 12, 30), Decimal("95"))


def test_last_adjusted_close_empty_ids(seed: Seed) -> None:
    assert last_adjusted_close_as_of(seed.session, [], D) == {}

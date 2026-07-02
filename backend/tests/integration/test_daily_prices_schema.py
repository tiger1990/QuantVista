"""daily_prices partitioning guarantees (QV-014) — verifies migration ``0004``.

The DDL for ``daily_prices`` (monthly RANGE partitions on ``date``) was authored in
``0004_prices_partitioned.py``; these tests lock in the properties the schema exists to
provide (``03`` §4.1/§9): correct partition routing, the ``create_month_partition()`` helper,
``(stock_id, date)`` uniqueness, ``NUMERIC`` money, and the global/no-RLS posture (rule #1).

Run as the admin role. All writes (and any partition the helper creates) happen inside a
transaction that is rolled back — Postgres DDL is transactional, so nothing survives.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


@pytest.fixture
def conn(admin_engine: Engine) -> Iterator[Connection]:
    """A connection in a transaction that is always rolled back (no residue)."""
    with admin_engine.connect() as connection:
        trans = connection.begin()
        try:
            yield connection
        finally:
            trans.rollback()


def _new_stock(conn: Connection) -> UUID:
    market_id, stock_id = uuid4(), uuid4()
    conn.execute(
        text(
            "INSERT INTO markets (id, code, name, country, currency, timezone) "
            "VALUES (:id, :code, 'Test Market', 'IN', 'INR', 'Asia/Kolkata')"
        ),
        {"id": market_id, "code": f"T{uuid4().hex[:6]}"},
    )
    conn.execute(
        text(
            "INSERT INTO stocks (id, market_id, symbol, company_name) "
            "VALUES (:id, :m, :sym, 'Test Co')"
        ),
        {"id": stock_id, "m": market_id, "sym": f"SYM{uuid4().hex[:6]}"},
    )
    return stock_id


def _insert_price(conn: Connection, stock_id: UUID, on: date) -> None:
    conn.execute(
        text(
            "INSERT INTO daily_prices (stock_id, date, open, high, low, close, adj_close, volume) "
            "VALUES (:s, :d, 100.5, 101.0, 99.5, 100.0, 100.0, 12345)"
        ),
        {"s": stock_id, "d": on},
    )


def _partition_of(conn: Connection, stock_id: UUID, on: date) -> str:
    return str(
        conn.execute(
            text(
                "SELECT tableoid::regclass::text FROM daily_prices "
                "WHERE stock_id = :s AND date = :d"
            ),
            {"s": stock_id, "d": on},
        ).scalar_one()
    )


# --- AC #2: partitioning + routing ------------------------------------------
def test_daily_prices_is_range_partitioned(conn: Connection) -> None:
    # Assert — relkind 'p' == partitioned table
    relkind = conn.execute(
        text("SELECT relkind FROM pg_class WHERE relname = 'daily_prices'")
    ).scalar_one()
    assert relkind == "p"


def test_row_routes_to_existing_month_partition(conn: Connection) -> None:
    # Arrange — the current month has a partition created by 0004
    stock_id = _new_stock(conn)
    today = date.today().replace(day=15)
    # Act
    _insert_price(conn, stock_id, today)
    # Assert — lands in the concrete monthly partition, not the default
    part = _partition_of(conn, stock_id, today)
    assert part == f"daily_prices_{today:%Y_%m}"


def test_row_without_month_partition_lands_in_default(conn: Connection) -> None:
    # Arrange — a far-past month has no dedicated partition
    stock_id = _new_stock(conn)
    old = date(2005, 3, 10)
    # Act
    _insert_price(conn, stock_id, old)
    # Assert
    assert _partition_of(conn, stock_id, old) == "daily_prices_default"


# --- AC #3: create_month_partition helper -----------------------------------
def test_create_month_partition_routes_new_month(conn: Connection) -> None:
    # Arrange — a month with no partition yet
    stock_id = _new_stock(conn)
    month_start = date(2009, 1, 1)
    day = date(2009, 1, 20)
    # Act — create the partition, then insert into that month
    conn.execute(text("SELECT create_month_partition('daily_prices', :m)"), {"m": month_start})
    _insert_price(conn, stock_id, day)
    # Assert — routes to the new named partition, not default
    assert _partition_of(conn, stock_id, day) == "daily_prices_2009_01"


def test_create_month_partition_is_idempotent(conn: Connection) -> None:
    # Act / Assert — a second call for the same month is a no-op (CREATE ... IF NOT EXISTS)
    month_start = date(2008, 6, 1)
    conn.execute(text("SELECT create_month_partition('daily_prices', :m)"), {"m": month_start})
    conn.execute(text("SELECT create_month_partition('daily_prices', :m)"), {"m": month_start})


# --- AC #4: uniqueness -------------------------------------------------------
def test_unique_stock_id_date(conn: Connection) -> None:
    # Arrange
    stock_id = _new_stock(conn)
    day = date.today().replace(day=10)
    _insert_price(conn, stock_id, day)
    # Act / Assert — duplicate (stock_id, date) rejected
    with pytest.raises(IntegrityError), conn.begin_nested():
        _insert_price(conn, stock_id, day)


# --- AC #5: NUMERIC money, not float ----------------------------------------
def test_money_columns_are_numeric(conn: Connection) -> None:
    types = {
        r[0]: r[1]
        for r in conn.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'daily_prices'"
            )
        )
    }
    for col in ("open", "high", "low", "close", "adj_close"):
        assert types[col] == "numeric", col
    assert types["volume"] == "bigint"


# --- AC #6: global / no-RLS --------------------------------------------------
def test_daily_prices_has_no_tenant_id_or_rls(conn: Connection) -> None:
    tenant_cols = conn.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'daily_prices' AND column_name = 'tenant_id'"
        )
    ).scalar_one()
    rls = conn.execute(
        text("SELECT relrowsecurity FROM pg_class WHERE relname = 'daily_prices'")
    ).scalar_one()
    policies = conn.execute(
        text("SELECT count(*) FROM pg_policies WHERE tablename = 'daily_prices'")
    ).scalar_one()
    assert tenant_cols == 0
    assert rls is False
    assert policies == 0


# --- AC #7: DTO alignment ----------------------------------------------------
def test_columns_cover_pricebar_dto(conn: Connection) -> None:
    cols = {
        r[0]
        for r in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'daily_prices'"
            )
        )
    }
    # PriceBar(symbol via stock_id, date, open, high, low, close, adj_close, volume, source)
    assert {
        "stock_id",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "source",
    } <= cols

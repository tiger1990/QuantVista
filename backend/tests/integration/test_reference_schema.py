"""Reference/master schema guarantees (QV-013) — verifies migration ``0003``.

The DDL for ``markets``/``stocks``/``index_constituents``/``corporate_actions`` was authored
in ``0003_reference_market.py``; these tests lock in the correctness properties the schema
exists to provide (``03`` §4.1/§5): survivorship-free history (``delisted_on``), point-in-time
index membership (one open row per index/stock), corporate-action uniqueness, and the
global/no-RLS posture (project rule #1). Run as the admin role — reference data is global.

All writes happen inside a transaction that is rolled back, so the shared reference tables
keep no residue. Constraint-violation checks use ``SAVEPOINT`` (``begin_nested``) so the outer
transaction stays usable.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

_GLOBAL_TABLES = ("markets", "stocks", "index_constituents", "corporate_actions")


@pytest.fixture
def conn(admin_engine: Engine) -> Iterator[Connection]:
    """A connection in a transaction that is always rolled back (no residue)."""
    with admin_engine.connect() as connection:
        trans = connection.begin()
        try:
            yield connection
        finally:
            trans.rollback()


def _new_market(conn: Connection) -> UUID:
    market_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO markets (id, code, name, country, currency, timezone) "
            "VALUES (:id, :code, 'Test Market', 'IN', 'INR', 'Asia/Kolkata')"
        ),
        {"id": market_id, "code": f"T{uuid4().hex[:6]}"},
    )
    return market_id


def _new_stock(
    conn: Connection,
    market_id: UUID,
    *,
    symbol: str | None = None,
    delisted_on: date | None = None,
    is_active: bool = True,
) -> UUID:
    stock_id = uuid4()
    conn.execute(
        text(
            "INSERT INTO stocks (id, market_id, symbol, company_name, delisted_on, is_active) "
            "VALUES (:id, :m, :sym, 'Test Co', :d, :active)"
        ),
        {
            "id": stock_id,
            "m": market_id,
            "sym": symbol or f"SYM{uuid4().hex[:6]}",
            "d": delisted_on,
            "active": is_active,
        },
    )
    return stock_id


# --- AC #2: survivorship-free stocks ----------------------------------------
def test_delisted_stock_stays_queryable(conn: Connection) -> None:
    # Arrange — a delisted name (delisted_on set, inactive)
    market_id = _new_market(conn)
    stock_id = _new_stock(conn, market_id, delisted_on=date(2020, 1, 1), is_active=False)
    # Act
    row = conn.execute(
        text("SELECT delisted_on, is_active FROM stocks WHERE id = :id"), {"id": stock_id}
    ).one()
    # Assert — delisted rows are never removed; they stay queryable (03 §5)
    assert row.delisted_on == date(2020, 1, 1)
    assert row.is_active is False


def test_active_stock_allows_null_delisted_on(conn: Connection) -> None:
    # Arrange / Act — delisted_on is nullable for live names
    market_id = _new_market(conn)
    stock_id = _new_stock(conn, market_id, delisted_on=None)
    # Assert
    got = conn.execute(
        text("SELECT delisted_on FROM stocks WHERE id = :id"), {"id": stock_id}
    ).scalar_one()
    assert got is None


def test_stocks_unique_market_symbol(conn: Connection) -> None:
    # Arrange
    market_id = _new_market(conn)
    _new_stock(conn, market_id, symbol="DUPSYM")
    # Act / Assert — same (market_id, symbol) is rejected
    with pytest.raises(IntegrityError), conn.begin_nested():
        _new_stock(conn, market_id, symbol="DUPSYM")


def test_stocks_isin_index_exists(conn: Connection) -> None:
    # Assert — the isin lookup index from 03 §4.1 is present
    names = {
        r[0]
        for r in conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'stocks'"))
    }
    assert "ix_stocks_isin" in names


# --- AC #3: point-in-time index membership ----------------------------------
def _add_membership(
    conn: Connection,
    stock_id: UUID,
    effective_from: date,
    effective_to: date | None,
    index_code: str = "NIFTY200",
) -> None:
    conn.execute(
        text(
            "INSERT INTO index_constituents "
            "(id, index_code, stock_id, effective_from, effective_to, weight) "
            "VALUES (gen_random_uuid(), :ic, :s, :ef, :et, 0.5)"
        ),
        {"ic": index_code, "s": stock_id, "ef": effective_from, "et": effective_to},
    )


def test_index_allows_one_open_membership_with_history(conn: Connection) -> None:
    # Arrange — a closed historical membership + a current (open) one coexist
    market_id = _new_market(conn)
    stock_id = _new_stock(conn, market_id)
    _add_membership(conn, stock_id, date(2020, 1, 1), date(2021, 1, 1))  # closed
    _add_membership(conn, stock_id, date(2021, 1, 2), None)  # open
    # Act / Assert — a SECOND open row for the same (index, stock) is rejected
    with pytest.raises(IntegrityError), conn.begin_nested():
        _add_membership(conn, stock_id, date(2022, 1, 1), None)


def test_index_membership_effective_to_after_from(conn: Connection) -> None:
    # Arrange
    market_id = _new_market(conn)
    stock_id = _new_stock(conn, market_id)
    # Act / Assert — effective_to must be strictly after effective_from
    with pytest.raises(IntegrityError), conn.begin_nested():
        _add_membership(conn, stock_id, date(2021, 6, 1), date(2021, 6, 1))


# --- AC #4: corporate_actions ------------------------------------------------
def _add_action(
    conn: Connection,
    stock_id: UUID,
    ex_date: date,
    action_type: str,
    *,
    with_details: bool = True,
) -> None:
    if with_details:
        conn.execute(
            text(
                "INSERT INTO corporate_actions "
                "(id, stock_id, ex_date, action_type, ratio_or_amount) "
                "VALUES (gen_random_uuid(), :s, :d, :t, 2.0)"
            ),
            {"s": stock_id, "d": ex_date, "t": action_type},
        )


def test_corporate_actions_unique_stock_exdate_type(conn: Connection) -> None:
    # Arrange
    market_id = _new_market(conn)
    stock_id = _new_stock(conn, market_id)
    _add_action(conn, stock_id, date(2026, 5, 2), "split")
    # Act / Assert — duplicate (stock_id, ex_date, action_type) rejected
    with pytest.raises(IntegrityError), conn.begin_nested():
        _add_action(conn, stock_id, date(2026, 5, 2), "split")


def test_corporate_actions_details_defaults_to_empty_jsonb(conn: Connection) -> None:
    # Arrange / Act — insert without details
    market_id = _new_market(conn)
    stock_id = _new_stock(conn, market_id)
    _add_action(conn, stock_id, date(2026, 6, 1), "dividend")
    details = conn.execute(
        text("SELECT details FROM corporate_actions WHERE stock_id = :s"), {"s": stock_id}
    ).scalar_one()
    # Assert
    assert details == {}


def test_corporate_actions_rejects_unknown_type(conn: Connection) -> None:
    # Arrange
    market_id = _new_market(conn)
    stock_id = _new_stock(conn, market_id)
    # Act / Assert — the action_type CHECK rejects an unknown value
    with pytest.raises(IntegrityError), conn.begin_nested():
        _add_action(conn, stock_id, date(2026, 7, 1), "spinoff")


# --- AC #5: global tables have no tenancy / RLS ------------------------------
@pytest.mark.parametrize("table", _GLOBAL_TABLES)
def test_global_table_has_no_tenant_id(conn: Connection, table: str) -> None:
    count = conn.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'tenant_id'"
        ),
        {"t": table},
    ).scalar_one()
    assert count == 0


@pytest.mark.parametrize("table", _GLOBAL_TABLES)
def test_global_table_has_no_rls(conn: Connection, table: str) -> None:
    rls = conn.execute(
        text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"), {"t": table}
    ).scalar_one()
    policies = conn.execute(
        text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": table}
    ).scalar_one()
    assert rls is False
    assert policies == 0


# --- AC #6: columns cover the QV-012 DTO fields they will persist ------------
def _columns(conn: Connection, table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
            {"t": table},
        )
    }


def test_columns_cover_qv012_dtos(conn: Connection) -> None:
    # corporate_actions ↔ CorporateAction DTO; stocks ↔ UniverseEntry DTO
    assert {"ex_date", "action_type", "ratio_or_amount", "details", "source"} <= _columns(
        conn, "corporate_actions"
    )
    assert {"symbol", "isin", "company_name", "sector", "is_active"} <= _columns(conn, "stocks")

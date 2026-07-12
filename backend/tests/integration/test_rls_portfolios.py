"""Cross-tenant RLS isolation for portfolios + portfolio_positions (QV-051) — the mandatory
denial gate (project-context rule #2). Runs as the NON-superuser app role via ``session_scope``
against real PostgreSQL: tenant A cannot see or modify tenant B's portfolios/positions, and an
unbound session sees nothing. Mirrors ``test_rls_isolation.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CursorResult, Engine, text
from sqlalchemy.orm import Session

from quantvista.core.db import session_scope

pytestmark = pytest.mark.integration


@pytest.fixture
def world(admin_engine: Engine) -> Iterator[dict[str, UUID]]:
    a, b, user, market, stock = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    pa, pb = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:a, 'PF-RLS-A'), (:b, 'PF-RLS-B')"),
            {"a": a, "b": b},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, email, status, mfa_enabled, created_at, updated_at) "
                "VALUES (:u, :e, 'active', false, now(), now())"
            ),
            {"u": user, "e": f"pf-rls-{user}@test.local"},
        )
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market, "c": f"T{uuid4().hex[:6]}"},
        )
        conn.execute(
            text(
                "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                "VALUES (:id, :m, :s, 'Co', 'IT')"
            ),
            {"id": stock, "m": market, "s": f"PF{uuid4().hex[:6]}"},
        )
        conn.execute(
            text(
                "INSERT INTO portfolios (id, tenant_id, user_id, name) VALUES "
                "(:pa, :a, :u, 'A-pf'), (:pb, :b, :u, 'B-pf')"
            ),
            {"pa": pa, "pb": pb, "a": a, "b": b, "u": user},
        )
        conn.execute(
            text(
                "INSERT INTO portfolio_positions (tenant_id, portfolio_id, stock_id, weight) "
                "VALUES (:a, :pa, :s, 0.5), (:b, :pb, :s, 0.5)"
            ),
            {"a": a, "b": b, "pa": pa, "pb": pb, "s": stock},
        )
    yield {"a": a, "b": b, "user": user, "stock": stock, "market": market, "pa": pa, "pb": pb}
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), {"a": a, "b": b})
        conn.execute(text("DELETE FROM stocks WHERE id = :s"), {"s": stock})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market})
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})


def _pf_names(session: Session) -> set[str]:
    return {row[0] for row in session.execute(text("SELECT name FROM portfolios")).all()}


def _pos_count(session: Session) -> int:
    return cast(int, session.execute(text("SELECT count(*) FROM portfolio_positions")).scalar_one())


def test_each_tenant_sees_only_its_own_portfolio(world: dict[str, UUID]) -> None:
    with session_scope(world["a"]) as session:
        assert _pf_names(session) == {"A-pf"}
    with session_scope(world["b"]) as session:
        assert _pf_names(session) == {"B-pf"}


def test_tenant_b_cannot_see_or_modify_tenant_a_portfolio(world: dict[str, UUID]) -> None:
    with session_scope(world["b"]) as session:
        assert "A-pf" not in _pf_names(session)
        updated = cast(
            "CursorResult[Any]",
            session.execute(text("UPDATE portfolios SET name = 'x' WHERE name = 'A-pf'")),
        )
        deleted = cast(
            "CursorResult[Any]",
            session.execute(text("DELETE FROM portfolios WHERE name = 'A-pf'")),
        )
        assert updated.rowcount == 0
        assert deleted.rowcount == 0
    with session_scope(world["a"]) as session:  # A's row intact
        assert _pf_names(session) == {"A-pf"}


def test_positions_are_tenant_isolated(world: dict[str, UUID]) -> None:
    with session_scope(world["a"]) as session:  # A sees only its 1 position
        assert _pos_count(session) == 1
    with session_scope(world["b"]) as session:  # B cannot touch A's position
        updated = cast(
            "CursorResult[Any]",
            session.execute(
                text("UPDATE portfolio_positions SET weight = 0 WHERE portfolio_id = :p"),
                {"p": world["pa"]},
            ),
        )
        assert updated.rowcount == 0


def test_no_tenant_context_denies_all_rows(world: dict[str, UUID]) -> None:
    with session_scope() as session:
        assert _pf_names(session) == set()
        assert _pos_count(session) == 0

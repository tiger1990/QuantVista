"""Portfolio repository CRUD on the RLS tenant session (QV-051) — real PostgreSQL.

Exercises create/list/get/count/delete for portfolios and upsert/list/delete for positions,
all through ``session_scope(tenant_id)`` (the non-superuser app role, so RLS applies). Money
columns round-trip as ``Decimal``. Tenant + market + stock are admin-seeded and torn down.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.core.db import session_scope
from quantvista.portfolio.repositories import (
    count_portfolios,
    create_portfolio,
    delete_portfolio,
    delete_position,
    get_portfolio,
    list_portfolios,
    list_positions,
    upsert_position,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def ctx(admin_engine: Engine) -> Iterator[dict[str, UUID]]:
    tenant, user, market, stock = uuid4(), uuid4(), uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:t, 'PF-Repo-Test')"), {"t": tenant}
        )
        conn.execute(
            text(
                "INSERT INTO users (id, email, status, mfa_enabled, created_at, updated_at) "
                "VALUES (:u, :e, 'active', false, now(), now())"
            ),
            {"u": user, "e": f"pf-{user}@test.local"},
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
    yield {"tenant": tenant, "user": user, "market": market, "stock": stock}
    with admin_engine.begin() as conn:  # tenant delete cascades portfolios/positions
        conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant})
        conn.execute(text("DELETE FROM stocks WHERE id = :s"), {"s": stock})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market})
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})


def test_create_list_get_count_delete(ctx: dict[str, UUID]) -> None:
    with session_scope(ctx["tenant"]) as s:
        p = create_portfolio(s, tenant_id=ctx["tenant"], user_id=ctx["user"], name="Growth")
        assert p["name"] == "Growth"
        assert p["benchmark"] == "NIFTY200_TRI"  # DB default
        assert p["base_currency"] == "INR"  # DB default
        assert count_portfolios(s) == 1
        got = get_portfolio(s, UUID(str(p["id"])))
        assert got is not None and got["name"] == "Growth"
        assert [row["id"] for row in list_portfolios(s)] == [p["id"]]
        assert delete_portfolio(s, UUID(str(p["id"]))) is True
        assert count_portfolios(s) == 0
        assert get_portfolio(s, UUID(str(p["id"]))) is None


def test_position_upsert_updates_same_pair(ctx: dict[str, UUID]) -> None:
    with session_scope(ctx["tenant"]) as s:
        p = create_portfolio(s, tenant_id=ctx["tenant"], user_id=ctx["user"], name="P")
        pid = UUID(str(p["id"]))
        pos = upsert_position(
            s,
            tenant_id=ctx["tenant"],
            portfolio_id=pid,
            stock_id=ctx["stock"],
            weight=Decimal("0.25"),
        )
        assert pos["weight"] == Decimal("0.250000")  # numeric(9,6)
        # upserting the same (portfolio, stock) UPDATEs the row, not a duplicate
        pos2 = upsert_position(
            s,
            tenant_id=ctx["tenant"],
            portfolio_id=pid,
            stock_id=ctx["stock"],
            weight=Decimal("0.5"),
        )
        assert pos2["id"] == pos["id"]
        assert pos2["weight"] == Decimal("0.500000")
        assert len(list_positions(s, pid)) == 1
        assert delete_position(s, pid, ctx["stock"]) is True
        assert list_positions(s, pid) == []

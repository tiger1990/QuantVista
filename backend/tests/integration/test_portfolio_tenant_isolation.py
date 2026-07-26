"""Portfolio multi-tenancy isolation proof (QV-061) — real app + PG + the non-superuser role.

Proves a tenant can NEVER see or mutate another tenant's portfolio, positions, risk snapshots, or
optimize/rebalance results. Two tenants A and B are registered; A owns a real, priced portfolio with
positions. Every portfolio-scoped endpoint hit by B against A's ``portfolio_id`` must return 404
(RLS makes A's rows invisible — indistinguishable from a non-existent portfolio, so there is no
existence oracle). Below the API, the RLS policies (``0008_portfolio_risk``) are exercised directly
on ``session_scope`` (the ``quantvista_app`` non-superuser role): B's session sees none of A's rows
and cannot write a row carrying A's ``tenant_id`` (WITH CHECK).

CI-gated: ``pytest.mark.integration`` → runs in the required ``backend-rls`` job (real Postgres).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from quantvista.api.app import create_app
from quantvista.core.db import session_scope
from quantvista.portfolio.repositories import (
    create_portfolio,
    list_portfolios,
    upsert_position,
)

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
_N_BARS = 130
_SECTORS = ["IT", "IT", "FIN", "FIN"]
_END = date.today()
_START = _END - timedelta(days=_N_BARS - 1)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(client: TestClient) -> tuple[str, str]:
    email = f"iso-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


def _tenant_id(admin_engine: Engine, email: str) -> UUID:
    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT m.tenant_id FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE u.email = :e"
            ),
            {"e": email},
        ).scalar_one()
        return UUID(str(row))


def _price_rows(stock_ids: list[UUID]) -> list[dict[str, object]]:
    rng = np.random.default_rng(11)
    factor = rng.standard_normal(_N_BARS)
    rows: list[dict[str, object]] = []
    for i, sid in enumerate(stock_ids):
        noise = rng.standard_normal(_N_BARS) * 0.008
        rets = (0.6 + 0.2 * i) * factor * 0.01 + noise + 0.0004
        price = 100.0
        for d in range(_N_BARS):
            price *= 1.0 + float(rets[d])
            rows.append(
                {"s": sid, "d": _START + timedelta(days=d), "c": Decimal(str(round(price, 4)))}
            )
    return rows


@pytest.fixture
def iso(admin_engine: Engine) -> Iterator[dict[str, Any]]:
    """Two tenants A + B; A owns a priced portfolio with positions (shares + targets)."""
    client = TestClient(create_app(), base_url="https://testserver")
    email_a, token_a = _register(client)
    email_b, token_b = _register(client)
    tenant_a = _tenant_id(admin_engine, email_a)
    tenant_b = _tenant_id(admin_engine, email_b)

    market = uuid4()
    stocks = [uuid4() for _ in _SECTORS]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market, "c": f"IS{uuid4().hex[:6]}"},
        )
        for sid, sector in zip(stocks, _SECTORS, strict=True):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :s, 'Co', :sec)"
                ),
                {"id": sid, "m": market, "s": f"ISO{uuid4().hex[:6]}", "sec": sector},
            )
        conn.execute(
            text(
                "INSERT INTO daily_prices "
                "(stock_id, date, close, adj_close, high, low, volume, source) "
                "VALUES (:s, :d, :c, :c, :c, :c, 1000, 'seed')"
            ),
            _price_rows(stocks),
        )
        conn.execute(
            text("INSERT INTO technical_indicators (stock_id, date, beta_1y) VALUES (:s, :d, :b)"),
            [{"s": stocks[i], "d": _END, "b": Decimal(str(0.8 + 0.2 * i))} for i in range(3)],
        )

    # A builds a real portfolio: shares + targets so /risk + /rebalance reach a 200 for A.
    a_pid = client.post("/api/v1/portfolios", json={"name": "A-pf"}, headers=_h(token_a)).json()[
        "data"
    ]["id"]
    for sid in stocks:
        client.put(
            f"/api/v1/portfolios/{a_pid}/positions/{sid}",
            json={"shares": "10", "avg_cost": "100", "target_weight": "0.25"},
            headers=_h(token_a),
        )

    yield {
        "client": client,
        "token_a": token_a,
        "token_b": token_b,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "a_pid": a_pid,
        "stocks": stocks,
        "admin": admin_engine,
    }

    with admin_engine.begin() as conn:
        for email in (email_a, email_b):
            conn.execute(
                text(
                    "DELETE FROM tenants WHERE id IN (SELECT m.tenant_id FROM memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
                ),
                {"e": email},
            )
            conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
        conn.execute(
            text("DELETE FROM technical_indicators WHERE stock_id = ANY(:i)"), {"i": stocks}
        )
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:i)"), {"i": stocks})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": stocks})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market})


# ---------------------------------------------------------------------------
# Task 1 — API cross-tenant denial (real foreign portfolio, not just unknown uuid)
# ---------------------------------------------------------------------------


def test_owner_reaches_the_endpoints(iso: dict[str, Any]) -> None:
    """Sanity: A (the owner) reaches the compute path — proving the 404s for B are ISOLATION,
    not a broken portfolio. Risk + rebalance return 200 for A; optimize is entitlement-gated
    (Free → 403) but crucially NOT 404 for the owner."""
    client, ta, pid = iso["client"], iso["token_a"], iso["a_pid"]
    assert client.get(f"/api/v1/portfolios/{pid}/risk", headers=_h(ta)).status_code == 200
    assert (
        client.post(
            f"/api/v1/portfolios/{pid}/rebalance", json={"drift_threshold": "0.05"}, headers=_h(ta)
        ).status_code
        == 200
    )
    # owner is Free-tier → 403 on optimize, but NOT 404 (the portfolio is theirs)
    assert (
        client.post(
            f"/api/v1/portfolios/{pid}/optimize",
            json={"method": "mean_variance", "objective": "max_sharpe"},
            headers=_h(ta),
        ).status_code
        == 403
    )


def test_foreign_tenant_gets_404_on_every_endpoint(iso: dict[str, Any]) -> None:
    """B must get 404 on A's portfolio across the WHOLE surface — including /optimize (404, not the
    403 that would leak the portfolio's existence before the ownership check)."""
    client, tb, pid, stock = iso["client"], iso["token_b"], iso["a_pid"], iso["stocks"][0]
    cases = [
        ("GET", f"/api/v1/portfolios/{pid}", None),
        ("DELETE", f"/api/v1/portfolios/{pid}", None),
        ("GET", f"/api/v1/portfolios/{pid}/positions", None),
        ("PUT", f"/api/v1/portfolios/{pid}/positions/{stock}", {"shares": "999"}),
        ("DELETE", f"/api/v1/portfolios/{pid}/positions/{stock}", None),
        ("GET", f"/api/v1/portfolios/{pid}/risk", None),
        ("POST", f"/api/v1/portfolios/{pid}/rebalance", {"drift_threshold": "0.05"}),
        (
            "POST",
            f"/api/v1/portfolios/{pid}/optimize",
            {"method": "mean_variance", "objective": "max_sharpe"},
        ),
    ]
    for method, url, body in cases:
        r = client.request(method, url, json=body, headers=_h(tb))
        assert r.status_code == 404, (method, url, r.status_code, r.text)
        assert r.json()["error"]["code"] == "not_found", (method, url, r.json())


def test_a_data_not_listed_for_b_and_unchanged_after_attacks(iso: dict[str, Any]) -> None:
    """B's list excludes A's portfolio; A's data is unchanged after B's failed write attempts."""
    client, ta, tb, pid, stock = (
        iso["client"],
        iso["token_a"],
        iso["token_b"],
        iso["a_pid"],
        iso["stocks"][0],
    )
    b_list = [p["id"] for p in client.get("/api/v1/portfolios", headers=_h(tb)).json()["data"]]
    assert pid not in b_list

    before = client.get(f"/api/v1/portfolios/{pid}/positions", headers=_h(ta)).json()["data"]
    # B's write + delete attempts (each 404) must not touch A's data
    client.put(
        f"/api/v1/portfolios/{pid}/positions/{stock}", json={"shares": "999"}, headers=_h(tb)
    )
    client.delete(f"/api/v1/portfolios/{pid}/positions/{stock}", headers=_h(tb))
    client.delete(f"/api/v1/portfolios/{pid}", headers=_h(tb))
    after = client.get(f"/api/v1/portfolios/{pid}/positions", headers=_h(ta)).json()["data"]
    assert after == before
    assert client.get(f"/api/v1/portfolios/{pid}", headers=_h(ta)).status_code == 200  # survives


# ---------------------------------------------------------------------------
# Task 2 — Repository / RLS-level denial (below the API)
# ---------------------------------------------------------------------------


def test_rls_hides_foreign_rows_from_repo_session(iso: dict[str, Any]) -> None:
    """On B's non-superuser session, A's portfolios/positions/risk_snapshots are invisible."""
    tenant_a, tenant_b = iso["tenant_a"], iso["tenant_b"]
    with session_scope(tenant_b) as s:
        assert list_portfolios(s) == []  # B owns none (RLS-scoped)
        # Direct RLS check: A's rows are filtered out entirely under B's binding.
        n_pf = s.execute(text("SELECT count(*) FROM portfolios")).scalar_one()
        n_pos = s.execute(text("SELECT count(*) FROM portfolio_positions")).scalar_one()
        assert n_pf == 0 and n_pos == 0
    # ...but A's own session sees A's portfolio (proving the data really exists).
    with session_scope(tenant_a) as s:
        assert len(list_portfolios(s)) == 1


def test_rls_with_check_blocks_writing_a_foreign_tenant_row(iso: dict[str, Any]) -> None:
    """A logic bug can't cross tenants: writing an A-tenant_id row under B's binding is refused."""
    tenant_a, tenant_b, user_b_pid = iso["tenant_a"], iso["tenant_b"], iso["a_pid"]
    # RLS WITH CHECK violation (SQLSTATE 42501) → SQLAlchemy DBAPIError.
    with session_scope(tenant_b) as s, pytest.raises(DBAPIError):
        create_portfolio(s, tenant_id=tenant_a, user_id=uuid4(), name="sneaky")
    # And B cannot upsert a position onto A's portfolio row (parent invisible / WITH CHECK).
    with session_scope(tenant_b) as s, pytest.raises(DBAPIError):
        upsert_position(
            s,
            tenant_id=tenant_a,
            portfolio_id=UUID(user_b_pid),
            stock_id=iso["stocks"][0],
            shares=1,
        )


# ---------------------------------------------------------------------------
# Task 3 — Risk-snapshot isolation
# ---------------------------------------------------------------------------


def test_risk_snapshot_isolation(iso: dict[str, Any]) -> None:
    """A's persisted risk snapshot is invisible to B (API 404 + repo), and stays A's."""
    client, ta, tb, pid = iso["client"], iso["token_a"], iso["token_b"], iso["a_pid"]
    tenant_a, tenant_b, admin = iso["tenant_a"], iso["tenant_b"], iso["admin"]

    # A computes risk → persists a risk_snapshots row.
    assert client.get(f"/api/v1/portfolios/{pid}/risk", headers=_h(ta)).status_code == 200
    with admin.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM risk_snapshots WHERE tenant_id = :t"), {"t": tenant_a}
        ).scalar_one()
    assert n >= 1  # snapshot exists for A

    # B cannot read it via the API (404) nor via a B-bound repo session.
    assert client.get(f"/api/v1/portfolios/{pid}/risk", headers=_h(tb)).status_code == 404
    with session_scope(tenant_b) as s:
        assert s.execute(text("SELECT count(*) FROM risk_snapshots")).scalar_one() == 0
    # A still sees its own snapshot under A's binding.
    with session_scope(tenant_a) as s:
        assert s.execute(text("SELECT count(*) FROM risk_snapshots")).scalar_one() >= 1

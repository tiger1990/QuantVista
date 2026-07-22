"""Risk endpoint end-to-end (QV-058) — real app + PG + auth + the RiskEngine.

Covers success (Decimal-string metrics + beta coverage + the research disclaimer), snapshot
persistence + idempotency, empty positions → 422, and cross-tenant/unknown → 404. A market + priced
stocks + `beta_1y` indicators are admin-seeded; risk needs no paid entitlement, so a plain
registered tenant is used. Numpy-only compute — no cvxpy import (unlike the optimize test).
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

from quantvista.api.app import create_app

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
_N_BARS = 130
_SECTORS = ["IT", "IT", "FIN", "FIN"]
_END = (
    date.today()
)  # seed the newest bars → route's `as_of = latest_price_date` lands on our series
_START = _END - timedelta(days=_N_BARS - 1)


def _register(client: TestClient) -> tuple[str, str]:
    email = f"qv-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


def _price_rows(stock_ids: list[UUID]) -> list[dict[str, object]]:
    rng = np.random.default_rng(7)
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


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[dict[str, Any]]:
    client = TestClient(create_app(), base_url="https://testserver")
    email, token = _register(client)
    market = uuid4()
    stocks = [uuid4() for _ in _SECTORS]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market, "c": f"T{uuid4().hex[:6]}"},
        )
        for sid, sector in zip(stocks, _SECTORS, strict=True):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :s, 'Co', :sec)"
                ),
                {"id": sid, "m": market, "s": f"RSK{uuid4().hex[:6]}", "sec": sector},
            )
        conn.execute(
            text(
                "INSERT INTO daily_prices "
                "(stock_id, date, close, adj_close, high, low, volume, source) "
                "VALUES (:s, :d, :c, :c, :c, :c, 1000, 'seed')"
            ),
            _price_rows(stocks),
        )
        # beta_1y for the first 3 stocks (the 4th has none → beta coverage 3/4).
        conn.execute(
            text("INSERT INTO technical_indicators (stock_id, date, beta_1y) VALUES (:s, :d, :b)"),
            [{"s": stocks[i], "d": _END, "b": Decimal(str(0.8 + 0.2 * i))} for i in range(3)],
        )
    yield {"client": client, "token": token, "stocks": stocks}
    with admin_engine.begin() as conn:
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


def _portfolio_with_holdings(client: TestClient, token: str, stocks: list[UUID]) -> str:
    pid = client.post("/api/v1/portfolios", json={"name": "Risk"}, headers=_h(token)).json()[
        "data"
    ]["id"]
    for sid in stocks:
        client.put(
            f"/api/v1/portfolios/{pid}/positions/{sid}",
            json={"shares": "10", "avg_cost": "100"},
            headers=_h(token),
        )
    return str(pid)


def test_risk_returns_metrics_and_persists(api: dict[str, Any], admin_engine: Engine) -> None:
    client, token, stocks = api["client"], api["token"], api["stocks"]
    pid = _portfolio_with_holdings(client, token, stocks)
    r = client.get(f"/api/v1/portfolios/{pid}/risk", headers=_h(token))
    assert r.status_code == 200
    data = r.json()["data"]
    # series metrics present (130 bars) as Decimal strings
    for key in ("volatility", "max_drawdown", "sharpe", "sortino", "hhi", "beta"):
        assert isinstance(data[key], str), (key, data[key])
    assert set(data["sector_exposure"]) == {"IT", "FIN"}
    assert data["beta_coverage"]["covered"] == 3 and data["beta_coverage"]["total"] == 4
    assert r.headers["X-QuantVista-Disclaimer"] == "research-only; not investment advice"
    assert r.json()["meta"]["disclaimer"] == "Research signal, not investment advice."
    # persisted exactly one snapshot row for (portfolio, as_of)
    with admin_engine.begin() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM risk_snapshots WHERE portfolio_id = :p"), {"p": UUID(pid)}
        ).scalar_one()
    assert n == 1


def test_risk_is_idempotent_per_day(api: dict[str, Any], admin_engine: Engine) -> None:
    client, token, stocks = api["client"], api["token"], api["stocks"]
    pid = _portfolio_with_holdings(client, token, stocks)
    client.get(f"/api/v1/portfolios/{pid}/risk", headers=_h(token))
    client.get(f"/api/v1/portfolios/{pid}/risk", headers=_h(token))  # same as_of → upsert, no dup
    with admin_engine.begin() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM risk_snapshots WHERE portfolio_id = :p"), {"p": UUID(pid)}
        ).scalar_one()
    assert n == 1


def test_risk_empty_portfolio_422(api: dict[str, Any]) -> None:
    client, token = api["client"], api["token"]
    pid = client.post("/api/v1/portfolios", json={"name": "Empty"}, headers=_h(token)).json()[
        "data"
    ]["id"]
    r = client.get(f"/api/v1/portfolios/{pid}/risk", headers=_h(token))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_risk_unknown_portfolio_404(api: dict[str, Any]) -> None:
    client, token = api["client"], api["token"]
    r = client.get(f"/api/v1/portfolios/{uuid4()}/risk", headers=_h(token))
    assert r.status_code == 404

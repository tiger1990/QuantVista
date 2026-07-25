"""Rebalance endpoint integration tests (QV-059).

POST /portfolios/{id}/rebalance — real app + PG + auth + RebalanceEngine.
Covers: success (Decimal-string fields, trade directions, disclaimer), empty portfolio
(422), no target weights (422), unknown portfolio (404), balanced portfolio (no trades).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from quantvista.api.app import create_app

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
_N_BARS = 10  # small — we only need latest closes, not a returns matrix
_END = date.today()
_START = _END - timedelta(days=_N_BARS - 1)


def _register(client: TestClient) -> tuple[str, str]:
    email = f"rb-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[dict[str, Any]]:
    client = TestClient(create_app(), base_url="https://testserver")
    email, token = _register(client)
    market = uuid4()
    stocks = [uuid4(), uuid4()]  # A, B
    closes = [Decimal("100"), Decimal("300")]  # A=100, B=300

    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market, "c": f"RB{uuid4().hex[:6]}"},
        )
        for sid, sym in zip(stocks, ["STOCKA", "STOCKB"], strict=True):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :s, 'Co', 'IT')"
                ),
                {"id": sid, "m": market, "s": sym},
            )
        # seed prices for latest_price_date to return something
        for sid, cl in zip(stocks, closes, strict=True):
            for d in range(_N_BARS):
                conn.execute(
                    text(
                        "INSERT INTO daily_prices "
                        "(stock_id, date, close, adj_close, high, low, volume, source) "
                        "VALUES (:s, :d, :c, :c, :c, :c, 1000, 'seed')"
                    ),
                    {"s": sid, "d": _START + timedelta(days=d), "c": cl},
                )

    yield {"client": client, "token": token, "stocks": stocks, "email": email}

    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM tenants WHERE id IN (SELECT m.tenant_id FROM memberships m "
                "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
            ),
            {"e": email},
        )
        conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:i)"), {"i": stocks})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": stocks})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market})


def _portfolio_with_positions(
    client: TestClient,
    token: str,
    stocks: list[UUID],
    *,
    shares: list[str] | None = None,
    targets: list[str | None] | None = None,
) -> str:
    pid = client.post("/api/v1/portfolios", json={"name": "Rebal"}, headers=_h(token)).json()[
        "data"
    ]["id"]
    for i, sid in enumerate(stocks):
        body: dict[str, Any] = {"shares": shares[i] if shares else "10", "avg_cost": "100"}
        if targets and targets[i] is not None:
            body["target_weight"] = targets[i]
        client.put(
            f"/api/v1/portfolios/{pid}/positions/{sid}",
            json=body,
            headers=_h(token),
        )
    return str(pid)


def test_rebalance_returns_trades_and_disclaimer(api: dict[str, Any]) -> None:
    """Success path: positions with targets that are off → trades returned as Decimal strings."""
    client, token, stocks = api["client"], api["token"], api["stocks"]
    # current MV: A=100*10=1000 (25%), B=300*10=3000 (75%)
    # targets: A=50%, B=50% → A underweight → buy A; B overweight → sell B
    pid = _portfolio_with_positions(
        client, token, stocks, shares=["10", "10"], targets=["0.50", "0.50"]
    )
    r = client.post(
        f"/api/v1/portfolios/{pid}/rebalance",
        json={"drift_threshold": "0.01"},
        headers=_h(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert isinstance(data["total_drift"], str)
    assert isinstance(data["needs_rebalance"], bool)
    assert data["needs_rebalance"] is True
    assert len(data["trades"]) == 2
    # Decimal string fields present in each trade
    for trade in data["trades"]:
        for key in ("current_weight", "target_weight", "delta_weight"):
            assert isinstance(trade[key], str)
    # Buy A (underweight), sell B (overweight)
    trade_a = next(t for t in data["trades"] if t["stock_id"] == str(stocks[0]))
    trade_b = next(t for t in data["trades"] if t["stock_id"] == str(stocks[1]))
    assert trade_a["direction"] == "buy"
    assert trade_b["direction"] == "sell"
    # Disclaimer
    assert r.headers["X-QuantVista-Disclaimer"] == "research-only; not investment advice"
    assert r.json()["meta"]["disclaimer"] == "Research signal, not investment advice."


def test_rebalance_balanced_portfolio_returns_empty_trades(api: dict[str, Any]) -> None:
    """Portfolio exactly at targets → trades=[], needs_rebalance=False."""
    client, token, stocks = api["client"], api["token"], api["stocks"]
    # MV: A=1000 (25%), B=3000 (75%); targets match → drift = 0
    pid = _portfolio_with_positions(
        client, token, stocks, shares=["10", "10"], targets=["0.25", "0.75"]
    )
    r = client.post(
        f"/api/v1/portfolios/{pid}/rebalance",
        json={"drift_threshold": "0.05"},
        headers=_h(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["trades"] == []
    assert data["needs_rebalance"] is False
    assert Decimal(data["total_drift"]) == Decimal("0")


def test_rebalance_empty_portfolio_422(api: dict[str, Any]) -> None:
    client, token = api["client"], api["token"]
    pid = client.post("/api/v1/portfolios", json={"name": "Empty"}, headers=_h(token)).json()[
        "data"
    ]["id"]
    r = client.post(f"/api/v1/portfolios/{pid}/rebalance", json={}, headers=_h(token))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_rebalance_no_target_weights_422(api: dict[str, Any]) -> None:
    """Positions exist but none have target_weight → 422."""
    client, token, stocks = api["client"], api["token"], api["stocks"]
    pid = _portfolio_with_positions(client, token, stocks, shares=["10", "10"])
    r = client.post(f"/api/v1/portfolios/{pid}/rebalance", json={}, headers=_h(token))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_rebalance_unknown_portfolio_404(api: dict[str, Any]) -> None:
    client, token = api["client"], api["token"]
    r = client.post(f"/api/v1/portfolios/{uuid4()}/rebalance", json={}, headers=_h(token))
    assert r.status_code == 404

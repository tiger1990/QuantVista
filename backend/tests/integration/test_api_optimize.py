"""Optimize endpoint end-to-end (QV-055) — real app + PG + auth + the QV-054 optimizer.

Covers success (weights sum to 1.0 + metrics + per-constraint status + the research disclaimer),
infeasible → 422 with the binding constraint, the Free-tier 403 (no `optimization` flag),
cross-tenant/unknown 404, an unimplemented method → 422, and empty positions → 422. A market +
priced stocks are admin-seeded; tenant A is upgraded to Pro so it holds the `optimization` flag.
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

pytest.importorskip("cvxpy")  # optimize handler pulls cvxpy (the optional [portfolio] extra)

from quantvista.api.app import create_app  # noqa: E402

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
_N_BARS = 130
_SECTORS = ["IT", "IT", "FIN", "FIN"]
# Seed bars ENDING today so they are the newest in the shared DB → the route's
# `as_of = latest_price_date` lands on our last bar and the 2y lookback covers the whole series.
_END = date.today()
_START = _END - timedelta(days=_N_BARS - 1)


def _register(client: TestClient) -> tuple[str, str]:
    email = f"qv-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


def _price_rows(stock_ids: list[UUID]) -> list[dict[str, object]]:
    """A 4-asset factor model → non-degenerate covariance + distinct means (feasible MV)."""
    rng = np.random.default_rng(42)
    factor = rng.standard_normal(_N_BARS)
    rows: list[dict[str, object]] = []
    for i, sid in enumerate(stock_ids):
        beta = 0.6 + 0.2 * i
        drift = 0.0004 + 0.0003 * i
        noise = rng.standard_normal(_N_BARS) * 0.008
        rets = beta * factor * 0.01 + noise + drift
        price = 100.0
        for d in range(_N_BARS):
            price *= 1.0 + float(rets[d])
            rows.append(
                {"s": sid, "d": _START + timedelta(days=d), "c": Decimal(str(round(price, 4)))}
            )
    return rows


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[dict[str, Any]]:
    client = TestClient(create_app(), base_url="https://testserver")
    email_pro, token_pro = _register(client)
    email_free, token_free = _register(client)
    email_quant, token_quant = _register(client)
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
                {"id": sid, "m": market, "s": f"OPT{uuid4().hex[:6]}", "sec": sector},
            )
        conn.execute(
            text(
                "INSERT INTO daily_prices "
                "(stock_id, date, close, adj_close, high, low, volume, source) "
                "VALUES (:s, :d, :c, :c, :c, :c, 1000, 'seed')"
            ),
            _price_rows(stocks),
        )
        # Upgrade the "pro" tenant (holds `optimization`) and the "quant" tenant (also holds
        # `optimization_advanced`, so it reaches the BL/HRP not-yet-available branch).
        for email, plan in ((email_pro, "pro"), (email_quant, "quant")):
            conn.execute(
                text(
                    "UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE code = :plan) "
                    "WHERE tenant_id IN (SELECT m.tenant_id FROM memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
                ),
                {"e": email, "plan": plan},
            )
    yield {
        "client": client,
        "pro": token_pro,
        "free": token_free,
        "quant": token_quant,
        "stocks": stocks,
    }
    with admin_engine.begin() as conn:
        for email in (email_pro, email_free, email_quant):
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


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _portfolio_with_positions(client: TestClient, token: str, stocks: list[UUID]) -> str:
    pid = client.post("/api/v1/portfolios", json={"name": "Opt"}, headers=_h(token)).json()["data"][
        "id"
    ]
    for sid in stocks:
        client.put(
            f"/api/v1/portfolios/{pid}/positions/{sid}",
            json={"shares": "10", "avg_cost": "100"},
            headers=_h(token),
        )
    return str(pid)


def _optimize(client: TestClient, token: str, pid: str, **body: Any) -> Any:
    payload: dict[str, Any] = {"method": "mean_variance", "objective": "max_sharpe", **body}
    return client.post(f"/api/v1/portfolios/{pid}/optimize", json=payload, headers=_h(token))


def test_optimize_success_returns_weights_and_disclaimer(api: dict[str, Any]) -> None:
    client, token, stocks = api["client"], api["pro"], api["stocks"]
    pid = _portfolio_with_positions(client, token, stocks)
    r = _optimize(client, token, pid, constraints={"max_weight": "0.5", "long_only": True})
    assert r.status_code == 200
    body = r.json()
    data = body["data"]
    assert set(data["weights"]) == {str(s) for s in stocks}
    total = sum(Decimal(w) for w in data["weights"].values())
    assert abs(total - Decimal(1)) <= Decimal("0.0001")
    assert isinstance(data["expected_return"], str) and isinstance(data["expected_volatility"], str)
    assert any(c["kind"] == "full_investment" for c in data["constraints"])
    assert r.headers["X-QuantVista-Disclaimer"] == "research-only; not investment advice"
    assert body["meta"]["disclaimer"] == "Research signal, not investment advice."


def test_optimize_infeasible_returns_binding(api: dict[str, Any]) -> None:
    client, token, stocks = api["client"], api["pro"], api["stocks"]
    pid = _portfolio_with_positions(client, token, stocks)
    r = _optimize(
        client, token, pid, objective="target_return", constraints={"target_return": "5.0"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "infeasible"


def test_optimize_free_tier_forbidden(api: dict[str, Any]) -> None:
    client, token, stocks = api["client"], api["free"], api["stocks"]
    # a Free tenant can still create 1 portfolio, but optimize is entitlement-gated
    pid = _portfolio_with_positions(client, token, stocks)
    r = _optimize(client, token, pid)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "entitlement_exceeded"


def test_optimize_unknown_portfolio_404(api: dict[str, Any]) -> None:
    client, token = api["client"], api["pro"]
    r = _optimize(client, token, str(uuid4()))
    assert r.status_code == 404


def test_optimize_risk_parity_returns_weights(api: dict[str, Any]) -> None:
    client, token, stocks = api["client"], api["pro"], api["stocks"]
    pid = _portfolio_with_positions(client, token, stocks)
    r = _optimize(client, token, pid, method="risk_parity", constraints={"max_weight": "0.6"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data["weights"]) == {str(s) for s in stocks}
    total = sum(Decimal(w) for w in data["weights"].values())
    assert abs(total - Decimal(1)) <= Decimal("0.0001")
    assert r.headers["X-QuantVista-Disclaimer"] == "research-only; not investment advice"


def test_optimize_unimplemented_method_422(api: dict[str, Any]) -> None:
    # A Quant tenant clears the `optimization_advanced` gate but BL/HRP aren't built yet → 422.
    client, token, stocks = api["client"], api["quant"], api["stocks"]
    pid = _portfolio_with_positions(client, token, stocks)
    r = _optimize(client, token, pid, method="hrp")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_optimize_advanced_method_forbidden_for_pro(api: dict[str, Any]) -> None:
    # Pro holds `optimization` but not `optimization_advanced` → BL/HRP are 403, not 422.
    client, token, stocks = api["client"], api["pro"], api["stocks"]
    pid = _portfolio_with_positions(client, token, stocks)
    r = _optimize(client, token, pid, method="black_litterman")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "entitlement_exceeded"


def test_optimize_empty_portfolio_422(api: dict[str, Any]) -> None:
    client, token = api["client"], api["pro"]
    pid = client.post("/api/v1/portfolios", json={"name": "Empty"}, headers=_h(token)).json()[
        "data"
    ]["id"]
    r = _optimize(client, token, str(pid))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"

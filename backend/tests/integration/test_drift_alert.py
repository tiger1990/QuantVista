"""Drift alert integration tests (QV-059).

Tests ``AlertEvaluationService.evaluate`` with ``scope="portfolio"`` + ``metric="drift"``
rules on a real DB. Verifies: drift rule fires when portfolio drifts above threshold,
does not fire when portfolio is balanced, deduplication prevents double-fire on same cycle.
Also verifies ``validate_condition`` accepts ``drift`` as a metric and the alert CRUD
endpoint accepts ``scope="portfolio"`` + ``metric="drift"``.
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

from quantvista.alerts.rules import validate_condition
from quantvista.alerts.services import AlertEvaluationService
from quantvista.api.app import create_app

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
_END = date.today()
_START = _END - timedelta(days=9)


def _register(client: TestClient) -> tuple[str, str]:
    email = f"drift-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_rule(client: TestClient, token: str, portfolio_id: UUID, threshold: float) -> str:
    r = client.post(
        "/api/v1/alerts",
        json={
            "scope": "portfolio",
            "target_id": str(portfolio_id),
            "condition": {"metric": "drift", "op": "gte", "value": threshold},
            "channel": "in_app",
        },
        headers=_h(token),
    )
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


def _event_count(engine: Engine, rule_id: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM alert_events WHERE alert_rule_id = :r"),
                {"r": rule_id},
            ).scalar_one()
        )


@pytest.fixture
def drift_env(admin_engine: Engine) -> Iterator[dict[str, Any]]:
    """Provision two stocks with prices, a portfolio with mismatched targets (drift=0.25)."""
    client = TestClient(create_app(), base_url="https://testserver")
    email, token = _register(client)
    market = uuid4()
    stocks = [uuid4(), uuid4()]
    # MV: A=10×100=1000 (25%), B=10×300=3000 (75%); targets: A=50%, B=50% → drift=0.25

    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market, "c": f"DA{uuid4().hex[:6]}"},
        )
        for sid, sym in zip(stocks, ["DRFTA", "DRFTB"], strict=True):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :s, 'Co', 'IT')"
                ),
                {"id": sid, "m": market, "s": sym},
            )
        closes = [Decimal("100"), Decimal("300")]
        for sid, cl in zip(stocks, closes, strict=True):
            for d in range(10):
                conn.execute(
                    text(
                        "INSERT INTO daily_prices "
                        "(stock_id, date, close, adj_close, high, low, volume, source) "
                        "VALUES (:s, :d, :c, :c, :c, :c, 1000, 'seed')"
                    ),
                    {"s": sid, "d": _START + timedelta(days=d), "c": cl},
                )

    # Create portfolio + positions with mismatched targets (A=50%, B=50% but MV=25/75)
    pid_str = client.post("/api/v1/portfolios", json={"name": "Drift"}, headers=_h(token)).json()[
        "data"
    ]["id"]
    pid = UUID(pid_str)
    for _i, sid in enumerate(stocks):
        client.put(
            f"/api/v1/portfolios/{pid}/positions/{sid}",
            json={"shares": "10", "avg_cost": "100", "target_weight": "0.50"},
            headers=_h(token),
        )

    yield {
        "client": client,
        "token": token,
        "email": email,
        "portfolio_id": pid,
        "stocks": stocks,
    }

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


# ---------------------------------------------------------------------------
# Rule validation
# ---------------------------------------------------------------------------


def test_drift_is_valid_metric() -> None:
    cond = validate_condition({"metric": "drift", "op": "gte", "value": 0.1})
    assert cond.metric == "drift"
    assert cond.value == 0.1


def test_drift_alert_rule_create_via_api(drift_env: dict[str, Any]) -> None:
    """POST /alerts creates a portfolio-scoped drift rule without error."""
    client, token, pid = drift_env["client"], drift_env["token"], drift_env["portfolio_id"]
    r = client.post(
        "/api/v1/alerts",
        json={
            "scope": "portfolio",
            "target_id": str(pid),
            "condition": {"metric": "drift", "op": "gte", "value": 0.10},
            "channel": "in_app",
        },
        headers=_h(token),
    )
    assert r.status_code == 201, r.json()
    data = r.json()["data"]
    assert data["scope"] == "portfolio"
    assert data["condition"]["metric"] == "drift"


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def test_drift_alert_fires_when_drift_exceeds_threshold(
    drift_env: dict[str, Any], admin_engine: Engine
) -> None:
    """Drift≈0.25 with threshold=0.10 → alert fires → 1 event in alert_events."""
    client, token, pid = drift_env["client"], drift_env["token"], drift_env["portfolio_id"]
    rule_id = _create_rule(client, token, pid, threshold=0.10)
    fired = AlertEvaluationService().evaluate(_END, "test")
    assert fired >= 1
    assert _event_count(admin_engine, rule_id) == 1


def test_drift_alert_does_not_fire_when_balanced(
    drift_env: dict[str, Any], admin_engine: Engine
) -> None:
    """Portfolio at targets (MV weights match 25/75) → drift≈0 → alert does NOT fire."""
    client, token, pid = drift_env["client"], drift_env["token"], drift_env["portfolio_id"]
    stocks = drift_env["stocks"]
    # Update targets to match actual MV weights: A=25%, B=75%
    for sid, tw in zip(stocks, ["0.25", "0.75"], strict=True):
        client.put(
            f"/api/v1/portfolios/{pid}/positions/{sid}",
            json={"shares": "10", "avg_cost": "100", "target_weight": tw},
            headers=_h(token),
        )
    rule_id = _create_rule(client, token, pid, threshold=0.05)
    AlertEvaluationService().evaluate(_END, "test")
    assert _event_count(admin_engine, rule_id) == 0


def test_drift_alert_deduplication(drift_env: dict[str, Any], admin_engine: Engine) -> None:
    """Second evaluate() call for the same cycle inserts no additional event (dedup key)."""
    client, token, pid = drift_env["client"], drift_env["token"], drift_env["portfolio_id"]
    rule_id = _create_rule(client, token, pid, threshold=0.05)
    svc = AlertEvaluationService()
    svc.evaluate(_END, "test")
    svc.evaluate(_END, "test")  # same cycle
    assert _event_count(admin_engine, rule_id) == 1

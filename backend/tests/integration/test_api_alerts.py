"""Alert rules end-to-end (QV-047) — real app + PG + auth, two tenants. Covers create/list/delete,
the Free-tier limit (403), an invalid condition (422), and cross-tenant RLS isolation. Users/tenants
cleaned up (alert_rules cascade)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from quantvista.api.app import create_app

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"


def _payload(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "scope": "stock",
        "target_id": str(uuid4()),
        "condition": {"metric": "composite_score", "op": "lt", "value": 50},
        "channel": "in_app",
    }
    p.update(over)
    return p


def _register(client: TestClient) -> tuple[str, str]:
    email = f"qv-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[tuple[TestClient, str, str]]:
    client = TestClient(create_app(), base_url="https://testserver")
    email_a, token_a = _register(client)
    email_b, token_b = _register(client)
    yield client, token_a, token_b
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


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_list_delete_round_trip(api: tuple[TestClient, str, str]) -> None:
    client, token, _ = api
    r = client.post("/api/v1/alerts", json=_payload(), headers=_h(token))
    assert r.status_code == 201
    rule = r.json()["data"]
    assert rule["scope"] == "stock" and rule["is_active"] is True
    assert rule["condition"] == {"metric": "composite_score", "op": "lt", "value": 50.0}

    listed = client.get("/api/v1/alerts", headers=_h(token)).json()["data"]
    assert len(listed) == 1 and listed[0]["id"] == rule["id"]

    assert client.delete(f"/api/v1/alerts/{rule['id']}", headers=_h(token)).status_code == 204
    assert client.get("/api/v1/alerts", headers=_h(token)).json()["data"] == []


def test_entitlement_limit_returns_403(api: tuple[TestClient, str, str]) -> None:
    client, token, _ = api
    for _ in range(3):  # Free tier: alerts = 3
        assert client.post("/api/v1/alerts", json=_payload(), headers=_h(token)).status_code == 201
    r = client.post("/api/v1/alerts", json=_payload(), headers=_h(token))
    assert r.status_code == 403 and r.json()["error"]["code"] == "entitlement_exceeded"


def test_invalid_condition_returns_422(api: tuple[TestClient, str, str]) -> None:
    client, token, _ = api
    bad = _payload(condition={"metric": "market_cap", "op": "lt", "value": 50})  # unknown metric
    r = client.post("/api/v1/alerts", json=bad, headers=_h(token))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_cross_tenant_isolation(api: tuple[TestClient, str, str]) -> None:
    # Both tenants own a rule → prove the RLS policy *scopes* (each sees only its own), not merely
    # that an empty tenant sees nothing. A stronger check than "B sees []".
    client, token_a, token_b = api
    a_id = client.post("/api/v1/alerts", json=_payload(), headers=_h(token_a)).json()["data"]["id"]
    b_id = client.post("/api/v1/alerts", json=_payload(), headers=_h(token_b)).json()["data"]["id"]
    assert a_id != b_id

    a_list = client.get("/api/v1/alerts", headers=_h(token_a)).json()["data"]
    b_list = client.get("/api/v1/alerts", headers=_h(token_b)).json()["data"]
    assert [r["id"] for r in a_list] == [a_id]  # A sees ONLY its own
    assert [r["id"] for r in b_list] == [b_id]  # B sees ONLY its own (never A's)

    # B cannot reach A's rule by id — the DELETE is RLS-scoped, so it matches no row → 404.
    assert client.delete(f"/api/v1/alerts/{a_id}", headers=_h(token_b)).status_code == 404
    assert [r["id"] for r in client.get("/api/v1/alerts", headers=_h(token_a)).json()["data"]] == [
        a_id
    ]  # A's rule survives B's cross-tenant delete attempt

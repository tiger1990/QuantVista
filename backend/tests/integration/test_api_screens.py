"""Saved screens end-to-end (QV-039) — real app + PG + auth, two tenants. Covers the create/list/
delete round-trip, the Free-tier limit (403), invalid criteria (422), duplicate name (409), and
cross-tenant RLS isolation. Users/tenants cleaned up (screens cascade)."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from quantvista.api.app import create_app

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
CRITERIA = {
    "market": "NSE",
    "filters": [{"field": "composite_score", "op": "gte", "value": 70}],
    "sort": "-composite_score",
}


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
    r = client.post(
        "/api/v1/screens", json={"name": "High composite", "criteria": CRITERIA}, headers=_h(token)
    )
    assert r.status_code == 201
    screen_id = r.json()["data"]["id"]

    listed = client.get("/api/v1/screens", headers=_h(token)).json()["data"]
    assert len(listed) == 1 and listed[0]["name"] == "High composite"

    assert client.delete(f"/api/v1/screens/{screen_id}", headers=_h(token)).status_code == 204
    assert client.get("/api/v1/screens", headers=_h(token)).json()["data"] == []


def test_entitlement_limit_returns_403(api: tuple[TestClient, str, str]) -> None:
    client, token, _ = api
    for i in range(3):  # Free tier: saved_screens = 3
        assert (
            client.post(
                "/api/v1/screens", json={"name": f"s{i}", "criteria": CRITERIA}, headers=_h(token)
            ).status_code
            == 201
        )
    r = client.post("/api/v1/screens", json={"name": "s4", "criteria": CRITERIA}, headers=_h(token))
    assert r.status_code == 403 and r.json()["error"]["code"] == "entitlement_exceeded"


def test_invalid_criteria_returns_422(api: tuple[TestClient, str, str]) -> None:
    client, token, _ = api
    bad = {"market": "NSE", "filters": [{"field": "id", "op": "eq", "value": "x"}], "sort": None}
    r = client.post("/api/v1/screens", json={"name": "bad", "criteria": bad}, headers=_h(token))
    assert r.status_code == 422


def test_duplicate_name_returns_409(api: tuple[TestClient, str, str]) -> None:
    client, token, _ = api
    client.post("/api/v1/screens", json={"name": "dup", "criteria": CRITERIA}, headers=_h(token))
    r = client.post(
        "/api/v1/screens", json={"name": "dup", "criteria": CRITERIA}, headers=_h(token)
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


def test_cross_tenant_isolation(api: tuple[TestClient, str, str]) -> None:
    client, token_a, token_b = api
    screen_id = client.post(
        "/api/v1/screens", json={"name": "A-only", "criteria": CRITERIA}, headers=_h(token_a)
    ).json()["data"]["id"]

    assert client.get("/api/v1/screens", headers=_h(token_b)).json()["data"] == []  # B sees none
    assert client.delete(f"/api/v1/screens/{screen_id}", headers=_h(token_b)).status_code == 404
    assert len(client.get("/api/v1/screens", headers=_h(token_a)).json()["data"]) == 1  # A intact

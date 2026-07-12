"""Portfolio & position CRUD end-to-end (QV-052) — real app + PG + auth, two tenants.

Covers portfolio create/list/get/delete, positions upsert/list/delete, the Free-tier limit (403),
weight over-allocation (422), Idempotency-Key replay/conflict, and cross-tenant RLS isolation (404).
A market + stock are admin-seeded for the position FKs; tenants/users cleaned up (rows cascade).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from quantvista.api.app import create_app

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"


def _register(client: TestClient) -> tuple[str, str]:
    email = f"qv-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[tuple[TestClient, str, str, UUID]]:
    client = TestClient(create_app(), base_url="https://testserver")
    email_a, token_a = _register(client)
    email_b, token_b = _register(client)
    market, stock = uuid4(), uuid4()
    with admin_engine.begin() as conn:
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
    yield client, token_a, token_b, stock
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
        conn.execute(text("DELETE FROM stocks WHERE id = :s"), {"s": stock})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market})


def _h(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


def _create(client: TestClient, token: str, **over: Any) -> Any:
    body: dict[str, Any] = {"name": "Growth"}
    body.update(over)
    return client.post("/api/v1/portfolios", json=body, headers=_h(token))


def test_portfolio_create_list_get_delete(api: tuple[TestClient, str, str, UUID]) -> None:
    client, token, _, _ = api
    r = _create(client, token)
    assert r.status_code == 201
    pf = r.json()["data"]
    assert pf["name"] == "Growth"
    assert pf["benchmark"] == "NIFTY200_TRI" and pf["base_currency"] == "INR"

    listed = client.get("/api/v1/portfolios", headers=_h(token)).json()["data"]
    assert [p["id"] for p in listed] == [pf["id"]]

    got = client.get(f"/api/v1/portfolios/{pf['id']}", headers=_h(token))
    assert got.status_code == 200 and got.json()["data"]["name"] == "Growth"

    assert client.delete(f"/api/v1/portfolios/{pf['id']}", headers=_h(token)).status_code == 204
    assert client.get(f"/api/v1/portfolios/{pf['id']}", headers=_h(token)).status_code == 404
    assert client.get("/api/v1/portfolios", headers=_h(token)).json()["data"] == []


def test_entitlement_limit_returns_403(api: tuple[TestClient, str, str, UUID]) -> None:
    client, token, _, _ = api
    assert _create(client, token).status_code == 201  # Free tier: portfolios = 1
    r = _create(client, token)
    assert r.status_code == 403 and r.json()["error"]["code"] == "entitlement_exceeded"


def test_positions_upsert_list_delete(api: tuple[TestClient, str, str, UUID]) -> None:
    client, token, _, stock = api
    pid = _create(client, token).json()["data"]["id"]
    url = f"/api/v1/portfolios/{pid}/positions/{stock}"

    r = client.put(url, json={"weight": "0.25", "target_weight": "0.25"}, headers=_h(token))
    assert r.status_code == 200
    assert r.json()["data"]["weight"] == "0.250000"  # numeric(9,6), money as string

    # upserting the same (portfolio, stock) updates, not duplicates
    r2 = client.put(url, json={"weight": "0.5"}, headers=_h(token))
    assert r2.json()["data"]["weight"] == "0.500000"
    positions = client.get(f"/api/v1/portfolios/{pid}/positions", headers=_h(token)).json()["data"]
    assert len(positions) == 1

    assert client.delete(url, headers=_h(token)).status_code == 204
    assert client.get(f"/api/v1/portfolios/{pid}/positions", headers=_h(token)).json()["data"] == []


def test_weight_over_one_rejected(api: tuple[TestClient, str, str, UUID]) -> None:
    client, token, _, stock = api
    pid = _create(client, token).json()["data"]["id"]
    # per-field bound at the DTO edge: weight > 1 → 422
    bad = client.put(
        f"/api/v1/portfolios/{pid}/positions/{stock}",
        json={"weight": "1.5"},
        headers=_h(token),
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"


def test_position_on_missing_portfolio_404(api: tuple[TestClient, str, str, UUID]) -> None:
    client, token, _, stock = api
    r = client.put(
        f"/api/v1/portfolios/{uuid4()}/positions/{stock}",
        json={"weight": "0.1"},
        headers=_h(token),
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_idempotency_replay_and_conflict(api: tuple[TestClient, str, str, UUID]) -> None:
    client, token, _, _ = api
    key = str(uuid4())
    first = client.post(
        "/api/v1/portfolios", json={"name": "Growth"}, headers=_h(token, **{"Idempotency-Key": key})
    )
    assert first.status_code == 201
    pid = first.json()["data"]["id"]

    # same key + same body → replays the original 201, no second row created
    replay = client.post(
        "/api/v1/portfolios", json={"name": "Growth"}, headers=_h(token, **{"Idempotency-Key": key})
    )
    assert replay.status_code == 201 and replay.json()["data"]["id"] == pid
    assert len(client.get("/api/v1/portfolios", headers=_h(token)).json()["data"]) == 1

    # same key + different body → 409 conflict
    conflict = client.post(
        "/api/v1/portfolios", json={"name": "Value"}, headers=_h(token, **{"Idempotency-Key": key})
    )
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "conflict"


def test_cross_tenant_isolation_is_404(api: tuple[TestClient, str, str, UUID]) -> None:
    client, token_a, token_b, _ = api
    a_id = _create(client, token_a, name="A-pf").json()["data"]["id"]
    b_id = _create(client, token_b, name="B-pf").json()["data"]["id"]
    assert a_id != b_id

    # each sees only its own (the stronger RLS check)
    assert [
        p["id"] for p in client.get("/api/v1/portfolios", headers=_h(token_a)).json()["data"]
    ] == [a_id]
    assert [
        p["id"] for p in client.get("/api/v1/portfolios", headers=_h(token_b)).json()["data"]
    ] == [b_id]

    # B cannot reach A's portfolio by id — RLS makes it invisible → 404
    assert client.get(f"/api/v1/portfolios/{a_id}", headers=_h(token_b)).status_code == 404
    assert client.delete(f"/api/v1/portfolios/{a_id}", headers=_h(token_b)).status_code == 404
    # A's portfolio survives B's cross-tenant delete attempt
    assert client.get(f"/api/v1/portfolios/{a_id}", headers=_h(token_a)).status_code == 200

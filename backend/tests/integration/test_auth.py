"""Auth flows end-to-end (QV-006) — register / login / refresh rotation / reuse / me.

Drives the real FastAPI app (TestClient) against the local/CI Postgres. The app uses the
non-superuser app role + privileged role per `quantvista.core.db`.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from quantvista.api.app import create_app

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def account(admin_engine: Engine) -> Iterator[dict[str, str]]:
    email = f"qv-{uuid4()}@test.local"
    yield {"email": email, "password": PASSWORD}
    # Cleanup: drop the tenant (cascades memberships/subscriptions) then the user
    # (cascades refresh_tokens).
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM tenants WHERE id IN ("
                "  SELECT m.tenant_id FROM memberships m JOIN users u ON u.id = m.user_id "
                "  WHERE u.email = :e)"
            ),
            {"e": email},
        )
        conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


def _client() -> TestClient:
    # https base URL so the Secure refresh cookie is sent back by httpx.
    return TestClient(create_app(), base_url="https://testserver")


def test_register_login_me_happy_path(account: dict[str, str]) -> None:
    client = _client()

    # Register → 201 + access token + refresh cookie
    r = client.post("/api/v1/auth/register", json={**account, "name": "Test User"})
    assert r.status_code == 201
    access = r.json()["data"]["access_token"]
    assert access
    assert client.cookies.get("qv_refresh")

    # /me reflects the owner + Free-plan entitlements
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    data = me.json()["data"]
    assert data["email"] == account["email"]
    assert data["role"] == "owner"
    assert "watchlists" in data["entitlements"]  # seeded Free-plan entitlement key

    # Duplicate registration → conflict
    dup = client.post("/api/v1/auth/register", json={**account, "name": "Dup"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"


def test_login_and_bad_credentials(account: dict[str, str]) -> None:
    client = _client()
    client.post("/api/v1/auth/register", json=account)

    ok = client.post("/api/v1/auth/login", json=account)
    assert ok.status_code == 200
    assert ok.json()["data"]["access_token"]

    bad = client.post("/api/v1/auth/login", json={**account, "password": "wrong"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "unauthenticated"

    # Unauthenticated /me
    assert client.get("/api/v1/me").status_code == 401


def test_refresh_rotation_and_reuse_detection(account: dict[str, str]) -> None:
    client = _client()
    client.post("/api/v1/auth/register", json=account)
    client.post("/api/v1/auth/login", json=account)

    r1 = client.cookies.get("qv_refresh")
    assert r1

    # Rotate: R1 -> R2 (client now holds R2)
    rot = client.post("/api/v1/auth/refresh")
    assert rot.status_code == 200
    r2 = client.cookies.get("qv_refresh")
    assert r2 and r2 != r1

    # Replay the OLD token R1 → reuse detected → 401 (and the family is revoked)
    reuse = client.post("/api/v1/auth/refresh", cookies={"qv_refresh": r1})
    assert reuse.status_code == 401

    # Because the family was revoked, the current token R2 no longer works either
    after = client.post("/api/v1/auth/refresh", cookies={"qv_refresh": r2})
    assert after.status_code == 401

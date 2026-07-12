"""Notification-center API end-to-end (QV-050) — real app + PG, two users. Covers list (newest
first), mark-all-read, and RLS/user isolation. Users/tenants cleaned up (notifications cascade)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from quantvista.api.app import create_app

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"


def _register(client: TestClient, admin_engine: Engine) -> tuple[str, str, UUID, UUID]:
    email = f"qv-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT u.id, m.tenant_id FROM users u JOIN memberships m ON m.user_id = u.id "
                "WHERE u.email = :e"
            ),
            {"e": email},
        ).one()
    return email, token, row[0], row[1]


def _seed_note(admin_engine: Engine, tenant_id: UUID, user_id: UUID, headline: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO notifications (tenant_id, user_id, type, payload) "
                "VALUES (:t, :u, 'alert', CAST(:p AS jsonb))"
            ),
            {"t": tenant_id, "u": user_id, "p": json.dumps({"headline": headline})},
        )


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[tuple[TestClient, dict[str, object], dict[str, object]]]:
    client = TestClient(create_app(), base_url="https://testserver")
    ea, ta, ua, tna = _register(client, admin_engine)
    eb, tb, ub, tnb = _register(client, admin_engine)
    a = {"email": ea, "token": ta, "user_id": ua, "tenant_id": tna}
    b = {"email": eb, "token": tb, "user_id": ub, "tenant_id": tnb}
    yield client, a, b
    with admin_engine.begin() as conn:
        for email in (ea, eb):
            conn.execute(
                text(
                    "DELETE FROM tenants WHERE id IN (SELECT m.tenant_id FROM memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
                ),
                {"e": email},
            )
            conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


def _h(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_and_mark_read(
    admin_engine: Engine, api: tuple[TestClient, dict[str, object], dict[str, object]]
) -> None:
    client, a, _ = api
    tenant_id, user_id = a["tenant_id"], a["user_id"]
    assert isinstance(tenant_id, UUID) and isinstance(user_id, UUID)
    _seed_note(admin_engine, tenant_id, user_id, "AAA composite < 50")
    _seed_note(admin_engine, tenant_id, user_id, "BBB pe < 20")

    listed = client.get("/api/v1/notifications", headers=_h(a["token"])).json()["data"]
    assert len(listed) == 2
    assert all(n["read_at"] is None for n in listed)

    marked = client.post("/api/v1/notifications/read", headers=_h(a["token"])).json()["data"]
    assert marked == {"marked_read": 2}
    after = client.get("/api/v1/notifications", headers=_h(a["token"])).json()["data"]
    assert all(n["read_at"] is not None for n in after)


def test_user_isolation(
    admin_engine: Engine, api: tuple[TestClient, dict[str, object], dict[str, object]]
) -> None:
    client, a, b = api
    ta, ua = a["tenant_id"], a["user_id"]
    assert isinstance(ta, UUID) and isinstance(ua, UUID)
    _seed_note(admin_engine, ta, ua, "A-only")

    assert len(client.get("/api/v1/notifications", headers=_h(a["token"])).json()["data"]) == 1
    assert client.get("/api/v1/notifications", headers=_h(b["token"])).json()["data"] == []
    # B marking read does not touch A's notifications
    assert client.post("/api/v1/notifications/read", headers=_h(b["token"])).json()["data"] == {
        "marked_read": 0
    }

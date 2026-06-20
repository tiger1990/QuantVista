"""Tenant-context + entitlement seam end-to-end (QV-007) — needs PostgreSQL.

Two guarantees, both against a real DB as the NON-superuser app role:

1. The ``get_tenant_session`` dependency binds ``app.tenant_id`` so RLS filters every query
   to the caller's tenant (the mandatory cross-tenant-denial gate, exercised through the
   actual API dependency — not just ``session_scope`` directly).
2. ``EntitlementService`` reads the QV-005 seed: a Free-plan tenant is denied ``api_access``
   / ``backtest`` (403 ``entitlement_exceeded``); a Quant-plan tenant is allowed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.api.app import create_app
from quantvista.api.deps import TenantSessionDep, get_tenant_context, require_entitlement
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import TenantContext

pytestmark = pytest.mark.integration


# --- fixtures ---


@pytest.fixture
def tenant_on_plan(admin_engine: Engine) -> Iterator[Callable[[str], UUID]]:
    """Factory: create a tenant subscribed to ``plan_code`` (admin-seeded). Cascade-cleaned."""
    created: list[UUID] = []

    def _make(plan_code: str) -> UUID:
        tid = uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name) VALUES (:t, :n)"),
                {"t": tid, "n": f"ent-{plan_code}-{tid}"},
            )
            conn.execute(
                text(
                    "INSERT INTO subscriptions "
                    "(tenant_id, plan_id, status, created_at, updated_at) "
                    "SELECT :t, p.id, 'active', now(), now() FROM plans p WHERE p.code = :c"
                ),
                {"t": tid, "c": plan_code},
            )
        created.append(tid)
        return tid

    yield _make
    with admin_engine.begin() as conn:
        for tid in created:
            conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})


def _client(ctx: TenantContext, feature: str = "backtest") -> TestClient:
    app = create_app()
    router = APIRouter(prefix="/api/v1")

    @router.get("/_probe/watchlists")
    def _watchlists(session: Session = TenantSessionDep) -> dict[str, list[str]]:
        names = [r[0] for r in session.execute(text("SELECT name FROM watchlists")).all()]
        return {"names": names}

    @router.get("/_probe/gated", dependencies=[require_entitlement(feature)])
    def _gated() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: ctx
    return TestClient(app, base_url="https://testserver")


def _ctx(tenant_id: UUID) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_id=uuid4(), role="owner")


# --- RLS isolation through the dependency ---


def test_tenant_session_binds_rls_and_isolates_rows(two_tenants: dict[str, UUID]) -> None:
    # Tenant A's request only ever sees A's rows...
    a = _client(_ctx(two_tenants["a"])).get("/api/v1/_probe/watchlists")
    assert a.status_code == 200
    assert a.json()["names"] == ["A-list"]

    # ...and tenant B's request only sees B's rows. RLS denial proven via get_tenant_session.
    b = _client(_ctx(two_tenants["b"])).get("/api/v1/_probe/watchlists")
    assert b.status_code == 200
    assert b.json()["names"] == ["B-list"]


# --- entitlement gate against the real seed ---


def test_free_plan_denied_capabilities(tenant_on_plan: Callable[[str], UUID]) -> None:
    free = tenant_on_plan("free")
    svc = EntitlementService()
    assert svc.is_allowed(free, "api_access") is False
    assert svc.is_allowed(free, "backtest") is False
    # And the API gate returns the canonical 403 envelope.
    for feature in ("api_access", "backtest"):
        r = _client(_ctx(free), feature=feature).get("/api/v1/_probe/gated")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "entitlement_exceeded"


def test_quant_plan_allows_capabilities(tenant_on_plan: Callable[[str], UUID]) -> None:
    quant = tenant_on_plan("quant")
    svc = EntitlementService()
    assert svc.is_allowed(quant, "api_access") is True
    r = _client(_ctx(quant), feature="api_access").get("/api/v1/_probe/gated")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_get_returns_seeded_free_entitlements(tenant_on_plan: Callable[[str], UUID]) -> None:
    free = tenant_on_plan("free")
    svc = EntitlementService()
    ents = svc.get(free)
    # Values come straight from seed_reference.sql (Free plan).
    assert ents.limit("saved_screens") == 3
    assert ents.is_allowed("api_access") is False
    assert svc.limit(free, "saved_screens") == 3  # service-level quota lookup

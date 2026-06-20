"""Unit tests for the QV-007 tenant-context + entitlement seam (no DB).

The DB-touching ``EntitlementService.get`` is covered by integration tests; here we test the
pure ``Entitlements`` logic, the ``TenantContext`` value object, and the API gate behaviour
(``require_entitlement`` → ``entitlement_exceeded``/403) with the service faked via
FastAPI dependency overrides.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from quantvista.api.app import create_app
from quantvista.api.deps import (
    get_entitlement_service,
    get_tenant_context,
    require_entitlement,
)
from quantvista.identity.interfaces import ITenantContext
from quantvista.identity.models import (
    Entitlement,
    EntitlementExceeded,
    Entitlements,
    TenantContext,
)

# --- Entitlements value object (pure) ---


def _free_like() -> Entitlements:
    return Entitlements(
        items={
            "saved_screens": Entitlement("saved_screens", limit=3, flag=None),  # quota
            "watchlist_items_unlimited": Entitlement(
                "watchlist_items_unlimited", limit=None, flag=None
            ),  # unlimited quota
            "api_access": Entitlement("api_access", limit=None, flag=False),  # capability off
            "backtest_full": Entitlement("backtest_full", limit=None, flag=True),  # capability on
        }
    )


def test_capability_flag_true_is_allowed() -> None:
    assert _free_like().is_allowed("backtest_full") is True


def test_capability_flag_false_is_not_allowed() -> None:
    assert _free_like().is_allowed("api_access") is False


def test_quota_key_present_is_allowed() -> None:
    # A limit-type key (numeric or unlimited) counts as granted; counting is enforced later.
    ents = _free_like()
    assert ents.is_allowed("saved_screens") is True
    assert ents.is_allowed("watchlist_items_unlimited") is True


def test_absent_key_is_not_allowed() -> None:
    assert _free_like().is_allowed("nonexistent_feature") is False


def test_limit_returns_quota_or_none() -> None:
    ents = _free_like()
    assert ents.limit("saved_screens") == 3
    assert ents.limit("watchlist_items_unlimited") is None  # unlimited
    assert ents.limit("api_access") is None  # capability key has no numeric limit
    assert ents.limit("absent") is None


# --- TenantContext value object ---


def test_tenant_context_satisfies_protocol_and_exposes_tenant_id() -> None:
    tid = uuid4()
    ctx = TenantContext(tenant_id=tid, user_id=uuid4(), role="owner")
    assert ctx.tenant_id == tid
    assert isinstance(ctx, ITenantContext)  # runtime_checkable Protocol


# --- API gate (require_entitlement) with the service faked ---


class _FakeEntitlements:
    """Stand-in EntitlementService: ``check`` raises for features not in ``allowed``."""

    def __init__(self, allowed: set[str]) -> None:
        self._allowed = allowed

    def check(self, tenant_id: object, feature: str) -> None:
        if feature not in self._allowed:
            raise EntitlementExceeded(feature)


def _gated_client(allowed: set[str]) -> TestClient:
    app: FastAPI = create_app()
    router = APIRouter(prefix="/api/v1")

    @router.get("/_probe/backtest", dependencies=[require_entitlement("backtest")])
    def _probe() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: TenantContext(
        tenant_id=uuid4(), user_id=uuid4(), role="owner"
    )
    app.dependency_overrides[get_entitlement_service] = lambda: _FakeEntitlements(allowed)
    return TestClient(app)


def test_gate_allows_when_feature_granted() -> None:
    r = _gated_client(allowed={"backtest"}).get("/api/v1/_probe/backtest")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_gate_denies_with_entitlement_exceeded_403() -> None:
    r = _gated_client(allowed=set()).get("/api/v1/_probe/backtest")
    assert r.status_code == 403
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "entitlement_exceeded"
    assert body["data"] is None

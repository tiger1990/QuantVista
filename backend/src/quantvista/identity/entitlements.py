"""Entitlement service (QV-007, stub) — plan limits/flags from the QV-005 seed.

Concrete ``IEntitlementService``. Answers "what does this tenant's plan grant?" by reading
``subscriptions → plans → entitlements``. ``subscriptions`` is RLS-scoped, so reads run in a
**tenant-bound** ``session_scope(tenant_id)``.

This is intentionally a stub: real Stripe-driven sync and a Redis ``ent:{tenant_id}`` cache
(busted on webhook) arrive in Sprint 10 (QV-074/075). The interface is final now.
"""

from __future__ import annotations

from uuid import UUID

from quantvista.core.db import session_scope
from quantvista.identity import repositories as repo
from quantvista.identity.models import Entitlement, EntitlementExceeded, Entitlements


class EntitlementService:
    """Concrete ``IEntitlementService`` (QV-007 stub)."""

    def get(self, tenant_id: UUID) -> Entitlements:
        """The tenant's active-plan entitlements. Empty when there is no subscription."""
        with session_scope(tenant_id) as session:  # RLS: subscriptions is tenant-scoped
            rows = repo.plan_entitlements(session, tenant_id)
        items = {key: Entitlement(key=key, limit=limit, flag=flag) for key, limit, flag in rows}
        return Entitlements(items=items)

    def is_allowed(self, tenant_id: UUID, feature: str) -> bool:
        """True if the tenant's plan grants ``feature`` (capability flag or present quota)."""
        return self.get(tenant_id).is_allowed(feature)

    def limit(self, tenant_id: UUID, key: str) -> int | None:
        """Numeric quota for ``key``; ``None`` = unlimited or not present."""
        return self.get(tenant_id).limit(key)

    def check(self, tenant_id: UUID, feature: str) -> None:
        """Raise ``EntitlementExceeded`` when ``feature`` is not granted (else no-op)."""
        if not self.is_allowed(tenant_id, feature):
            raise EntitlementExceeded(feature)

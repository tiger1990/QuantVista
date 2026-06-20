"""Identity & Tenancy published interfaces.

Depended on by all contexts (for tenant context); depends on no domain context.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from quantvista.identity.models import Entitlements, IssuedTokens, MeView, Principal


@runtime_checkable
class ITenantContext(Protocol):
    """Request-scoped tenant binding backing Postgres RLS (`SET LOCAL app.tenant_id`)."""

    @property
    def tenant_id(self) -> UUID: ...


@runtime_checkable
class IAuthService(Protocol):
    """Authentication: register/login, JWT issuance, rotating refresh, profile."""

    def register(self, email: str, password: str, name: str | None) -> Principal: ...

    def authenticate(self, email: str, password: str) -> Principal: ...

    def issue_tokens(self, principal: Principal) -> IssuedTokens: ...

    def rotate(self, raw_refresh: str) -> IssuedTokens: ...

    def logout(self, raw_refresh: str) -> None: ...

    def me(self, principal: Principal) -> MeView: ...


@runtime_checkable
class IEntitlementService(Protocol):
    """Plan/entitlement checks gating features and quotas per tenant.

    Final surface (QV-007). The Sprint-10 Stripe sync (QV-074/075) swaps the backing data
    source + adds a cache, but does not change this contract.
    """

    def get(self, tenant_id: UUID) -> Entitlements: ...

    def is_allowed(self, tenant_id: UUID, feature: str) -> bool: ...

    def limit(self, tenant_id: UUID, key: str) -> int | None: ...

    def check(self, tenant_id: UUID, feature: str) -> None: ...

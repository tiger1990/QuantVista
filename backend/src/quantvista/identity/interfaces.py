"""Identity & Tenancy published interfaces.

Depended on by all contexts (for tenant context); depends on no domain context.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class ITenantContext(Protocol):
    """Request-scoped tenant binding backing Postgres RLS (`SET LOCAL app.tenant_id`)."""

    @property
    def tenant_id(self) -> UUID: ...


@runtime_checkable
class IAuthService(Protocol):
    """Authentication: register/login, JWT issuance, refresh rotation."""

    def verify_credentials(self, email: str, password: str) -> UUID | None: ...


@runtime_checkable
class IEntitlementService(Protocol):
    """Plan/entitlement checks gating features and quotas per tenant."""

    def is_allowed(self, tenant_id: UUID, feature: str) -> bool: ...

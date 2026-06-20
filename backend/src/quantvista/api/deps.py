"""FastAPI dependencies for the API composition root.

The tenant seam (QV-007) is dependency-based, not ASGI middleware: RLS binds *per
transaction* (`core.db.session_scope`), so we resolve the tenant from the verified token
and open a tenant-bound session as the unit of work — consistent with that model.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast
from uuid import UUID

import jwt
from fastapi import Depends, Request, params
from sqlalchemy.orm import Session

from quantvista.core.db import session_scope
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import InvalidCredentials, Principal, TenantContext
from quantvista.identity.security import decode_access_token
from quantvista.identity.services import AuthService


def get_auth_service() -> AuthService:
    return AuthService()


def get_entitlement_service() -> EntitlementService:
    return EntitlementService()


def get_current_principal(request: Request) -> Principal:
    """Resolve the caller from the `Authorization: Bearer <jwt>` header."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise InvalidCredentials("missing bearer token")
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise InvalidCredentials("invalid token") from exc
    return Principal(
        user_id=UUID(claims["sub"]),
        tenant_id=UUID(claims["tenant_id"]),
        role=str(claims["role"]),
    )


def get_tenant_context(principal: Principal = Depends(get_current_principal)) -> TenantContext:
    """Active tenant context, derived only from the verified access token."""
    return TenantContext(
        tenant_id=principal.tenant_id, user_id=principal.user_id, role=principal.role
    )


def get_tenant_session(
    ctx: TenantContext = Depends(get_tenant_context),
) -> Iterator[Session]:
    """Yield a DB session bound to the caller's tenant (`SET LOCAL app.tenant_id`).

    Every query in the request unit of work runs under RLS for this tenant only. The
    binding lives exactly one transaction (committed/rolled back by ``session_scope``).
    """
    with session_scope(ctx.tenant_id) as session:
        yield session


def require_entitlement(feature: str) -> params.Depends:
    """Build a dependency that 403s (`entitlement_exceeded`) unless the plan grants ``feature``."""

    def _require(
        ctx: TenantContext = Depends(get_tenant_context),
        svc: EntitlementService = Depends(get_entitlement_service),
    ) -> None:
        svc.check(ctx.tenant_id, feature)

    return cast(params.Depends, Depends(_require))


CurrentPrincipal = Depends(get_current_principal)
AuthServiceDep = Depends(get_auth_service)
TenantContextDep = Depends(get_tenant_context)
TenantSessionDep = Depends(get_tenant_session)
EntitlementServiceDep = Depends(get_entitlement_service)

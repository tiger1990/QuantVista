"""identity domain types (QV-006)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated subject + active tenant context."""

    user_id: UUID
    tenant_id: UUID
    role: str


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token_raw: str  # opaque value handed to the client (cookie/body); never stored raw


@dataclass(frozen=True, slots=True)
class MeView:
    user_id: UUID
    email: str
    name: str | None
    tenant_id: UUID
    tenant_name: str
    role: str
    entitlements: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Request-scoped tenant binding resolved from the verified access token.

    Concrete ``ITenantContext`` (`identity.interfaces`). Carries the active tenant plus the
    caller's identity so the API can open a tenant-bound, RLS-enforced DB session
    (`SET LOCAL app.tenant_id`). Never built from request input — only from JWT claims.
    """

    tenant_id: UUID
    user_id: UUID
    role: str


@dataclass(frozen=True, slots=True)
class Entitlement:
    """One plan entitlement: either a numeric quota (``limit``) or a capability (``flag``).

    Rows carry ``limit_int`` xor ``flag_bool`` (or both NULL ⇒ unlimited quota). ``limit``
    is ``None`` for unlimited; ``flag`` is ``None`` for non-capability (limit-type) keys.
    """

    key: str
    limit: int | None
    flag: bool | None


@dataclass(frozen=True, slots=True)
class Entitlements:
    """A tenant's active-plan entitlements (value object; read from the QV-005 seed)."""

    items: dict[str, Entitlement] = field(default_factory=dict)

    def is_allowed(self, feature: str) -> bool:
        """True if ``feature`` is granted by the plan.

        - capability key (``flag`` set) ⇒ the flag value;
        - limit-type key present (quota number or unlimited) ⇒ granted (per-feature code
          enforces the actual count later);
        - absent key ⇒ not granted.
        """
        ent = self.items.get(feature)
        if ent is None:
            return False
        if ent.flag is not None:
            return ent.flag
        return True  # limit-type key is present ⇒ granted

    def limit(self, key: str) -> int | None:
        """Numeric quota for ``key``; ``None`` = unlimited *or* key absent."""
        ent = self.items.get(key)
        return ent.limit if ent is not None else None


# --- domain errors (mapped to envelope codes in the API layer) ---


class EmailAlreadyExists(Exception):
    """Registration with an email that already exists."""


class InvalidCredentials(Exception):
    """Bad email/password on login."""


class InvalidRefreshToken(Exception):
    """Unknown/expired/revoked refresh token — includes detected reuse."""


class EntitlementExceeded(Exception):
    """Caller's plan does not grant the requested feature (→ ``entitlement_exceeded``/403)."""

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(f"plan does not grant '{feature}'")

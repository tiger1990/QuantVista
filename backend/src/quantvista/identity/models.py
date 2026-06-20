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


# --- domain errors (mapped to envelope codes in the API layer) ---


class EmailAlreadyExists(Exception):
    """Registration with an email that already exists."""


class InvalidCredentials(Exception):
    """Bad email/password on login."""


class InvalidRefreshToken(Exception):
    """Unknown/expired/revoked refresh token — includes detected reuse."""

"""Authentication security primitives — Argon2id hashing, access JWTs, refresh tokens.

Stdlib + argon2-cffi + PyJWT only. No DB, no other context — keeps `identity` a clean
DAG foundation. Refresh tokens are opaque random strings; only their SHA-256 hash is ever
persisted (never the raw value).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from quantvista.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id is argon2-cffi's default variant


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except Argon2Error:
        return False


def create_access_token(user_id: UUID, tenant_id: UUID, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + verify an access JWT. Raises `jwt.PyJWTError` on invalid/expired tokens."""
    settings = get_settings()
    claims: dict[str, Any] = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    if claims.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return claims


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Return (raw, sha256_hash). The raw value goes to the client; the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)

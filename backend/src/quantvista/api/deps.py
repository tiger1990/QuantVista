"""FastAPI dependencies for the API composition root."""

from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import Depends, Request

from quantvista.identity.models import InvalidCredentials, Principal
from quantvista.identity.security import decode_access_token
from quantvista.identity.services import AuthService


def get_auth_service() -> AuthService:
    return AuthService()


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


CurrentPrincipal = Depends(get_current_principal)
AuthServiceDep = Depends(get_auth_service)

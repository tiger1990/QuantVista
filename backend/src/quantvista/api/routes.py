"""Auth + profile routes (QV-006). All responses use the standard envelope."""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response

from quantvista.api.deps import get_auth_service, get_current_principal
from quantvista.core.config import get_settings
from quantvista.identity.models import InvalidRefreshToken, Principal
from quantvista.identity.services import AuthService
from quantvista.schemas.auth import LoginRequest, MeResponse, RegisterRequest, TokenResponse
from quantvista.schemas.envelope import Envelope

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.refresh_cookie_name,
        value=raw,
        httponly=True,
        secure=s.cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], s.cookie_samesite),
        path="/api/v1/auth",
        max_age=s.refresh_token_ttl_seconds,
    )


def _tokens(access_token: str) -> dict[str, Any]:
    return TokenResponse(access_token=access_token).model_dump()


@router.post("/auth/register", response_model=None, status_code=201)
def register(
    body: RegisterRequest, response: Response, svc: AuthService = Depends(get_auth_service)
) -> Envelope[dict[str, Any]]:
    principal = svc.register(body.email, body.password, body.name)
    tokens = svc.issue_tokens(principal)
    _set_refresh_cookie(response, tokens.refresh_token_raw)
    return Envelope.ok(_tokens(tokens.access_token))


@router.post("/auth/login", response_model=None)
def login(
    body: LoginRequest, response: Response, svc: AuthService = Depends(get_auth_service)
) -> Envelope[dict[str, Any]]:
    principal = svc.authenticate(body.email, body.password)
    tokens = svc.issue_tokens(principal)
    _set_refresh_cookie(response, tokens.refresh_token_raw)
    return Envelope.ok(_tokens(tokens.access_token))


@router.post("/auth/refresh", response_model=None)
def refresh(
    request: Request, response: Response, svc: AuthService = Depends(get_auth_service)
) -> Envelope[dict[str, Any]]:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    if not raw:
        raise InvalidRefreshToken("missing")
    tokens = svc.rotate(raw)
    _set_refresh_cookie(response, tokens.refresh_token_raw)
    return Envelope.ok(_tokens(tokens.access_token))


@router.post("/auth/logout", response_model=None)
def logout(
    request: Request, response: Response, svc: AuthService = Depends(get_auth_service)
) -> Envelope[dict[str, Any]]:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    if raw:
        svc.logout(raw)
    response.delete_cookie(get_settings().refresh_cookie_name, path="/api/v1/auth")
    return Envelope.ok({"status": "logged-out"})


@router.get("/me", response_model=None)
def me(
    principal: Principal = Depends(get_current_principal),
    svc: AuthService = Depends(get_auth_service),
) -> Envelope[dict[str, Any]]:
    view = svc.me(principal)
    data = MeResponse(
        user_id=str(view.user_id),
        email=view.email,
        name=view.name,
        tenant_id=str(view.tenant_id),
        tenant_name=view.tenant_name,
        role=view.role,
        entitlements=view.entitlements,
    ).model_dump()
    return Envelope.ok(data)

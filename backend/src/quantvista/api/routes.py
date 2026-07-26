"""Auth + profile routes (QV-006). All responses use the standard envelope.

CSRF-SAFE (QV-079): every state-changing endpoint authenticates via ``Authorization: Bearer <jwt>``
— a header the browser never auto-attaches cross-origin, so classic cookie-CSRF does not apply. The
only cookie is the httpOnly, ``SameSite=lax`` refresh token, read solely by ``POST /auth/refresh``
(SameSite=lax withholds cookies on cross-site POSTs) and by ``POST /auth/logout`` (which only
deletes it — no state at risk). No CSRF token layer is therefore required. Auth endpoints are
additionally per-IP rate limited (see ``api.ratelimit``).
"""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response

from quantvista.api.deps import get_auth_service, get_current_principal
from quantvista.api.ratelimit import RATE_LIMITS, limiter
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


@router.post("/auth/register", response_model=Envelope[TokenResponse], status_code=201)
@limiter.limit(RATE_LIMITS["register"])
def register(
    request: Request,
    body: RegisterRequest,
    response: Response,
    svc: AuthService = Depends(get_auth_service),
) -> Envelope[dict[str, Any]]:
    principal = svc.register(body.email, body.password, body.name)
    tokens = svc.issue_tokens(principal)
    _set_refresh_cookie(response, tokens.refresh_token_raw)
    return Envelope.ok(_tokens(tokens.access_token))


@router.post("/auth/login", response_model=Envelope[TokenResponse])
@limiter.limit(RATE_LIMITS["login"])
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    svc: AuthService = Depends(get_auth_service),
) -> Envelope[dict[str, Any]]:
    principal = svc.authenticate(body.email, body.password)
    tokens = svc.issue_tokens(principal)
    _set_refresh_cookie(response, tokens.refresh_token_raw)
    return Envelope.ok(_tokens(tokens.access_token))


@router.post("/auth/refresh", response_model=Envelope[TokenResponse])
@limiter.limit(RATE_LIMITS["refresh"])
def refresh(
    request: Request, response: Response, svc: AuthService = Depends(get_auth_service)
) -> Envelope[dict[str, Any]]:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    if not raw:
        raise InvalidRefreshToken("missing")
    tokens = svc.rotate(raw)
    _set_refresh_cookie(response, tokens.refresh_token_raw)
    return Envelope.ok(_tokens(tokens.access_token))


@router.post("/auth/logout", response_model=Envelope[dict[str, str]])
def logout(
    request: Request, response: Response, svc: AuthService = Depends(get_auth_service)
) -> Envelope[dict[str, Any]]:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    if raw:
        svc.logout(raw)
    response.delete_cookie(get_settings().refresh_cookie_name, path="/api/v1/auth")
    return Envelope.ok({"status": "logged-out"})


@router.get("/me", response_model=Envelope[MeResponse])
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

"""Security response-header middleware (QV-079) — OWASP ASVS L2 baseline.

Stamps the standard hardening headers on every API response. The API returns JSON only, so
the CSP is the most restrictive possible (`default-src 'none'`) — with one exception: the
Swagger/ReDoc doc paths load JS/CSS from a CDN and would be blanked by that CSP, so they are
exempt from the CSP header (all other headers still apply).

Added as the OUTERMOST middleware in ``create_app`` so it stamps headers on the final response
even after ``RequestContextMiddleware`` rebuilds JSON envelopes. Uses ``setdefault`` so it never
clobbers a header an inner layer intentionally set. HSTS is opt-in (``hsts_enabled``) — off in
local/CI where there is no TLS, on in staging/prod.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Headers safe to apply to EVERY response, including the doc pages.
_BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # Disabled intentionally: modern browsers rely on CSP; the legacy filter causes bugs.
    "X-XSS-Protection": "0",
}
_CSP = "default-src 'none'; frame-ancestors 'none'"
# Paths whose HTML/JS/CSS load from a CDN — the strict CSP would blank them.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")

_HSTS = "max-age=31536000; includeSubDomains"

_Call = Callable[[Request], Awaitable[Response]]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply OWASP-baseline security headers to every response."""

    def __init__(self, app: ASGIApp, *, hsts_enabled: bool = False) -> None:
        super().__init__(app)
        headers = dict(_BASE_HEADERS)
        if hsts_enabled:
            headers["Strict-Transport-Security"] = _HSTS
        self._headers = headers

    async def dispatch(self, request: Request, call_next: _Call) -> Response:
        response = await call_next(request)
        for key, value in self._headers.items():
            response.headers.setdefault(key, value)
        if not request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
            response.headers.setdefault("Content-Security-Policy", _CSP)
        return response

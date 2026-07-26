"""Per-IP rate limiting for auth endpoints (QV-079).

Thin wrapper over ``slowapi`` (which wraps the ``limits`` library). The limiter is a MODULE
GLOBAL because the ``@limiter.limit(...)`` decorator must bind a stable object at import time.
It is created ``enabled`` per ``Settings.rate_limit_enabled`` — **OFF by default** so the test
suite is unaffected (every ``TestClient`` request shares the constant key ``"testclient"``, so an
on-by-default limiter would blow the window across unrelated tests). Real environments set
``RATE_LIMIT_ENABLED=true`` and, in prod, ``RATE_LIMIT_BACKEND=redis``.

We deliberately do NOT add ``SlowAPIMiddleware`` — per-route decorated limits only need the
limiter on ``app.state`` plus an exception handler. ``create_app`` wires both. The 429 response is
rebuilt into the project envelope, and slowapi's ``_inject_headers`` adds the ``Retry-After`` +
``X-RateLimit-*`` headers computed from the breached limit's window.
"""

from __future__ import annotations

from fastapi.encoders import jsonable_encoder
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from quantvista.core.config import get_settings
from quantvista.schemas.envelope import Envelope


def _storage_uri() -> str:
    settings = get_settings()
    return settings.redis_url if settings.rate_limit_backend == "redis" else "memory://"


# Module-global so the route decorators can bind at import time. `headers_enabled` makes
# `_inject_headers` populate Retry-After + X-RateLimit-* — we call it only in the 429 handler
# (no SlowAPIMiddleware), so those headers appear on rate-limited responses only.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_storage_uri(),
    enabled=get_settings().rate_limit_enabled,
    headers_enabled=True,
    default_limits=[],
)

# Per-endpoint limits (fixed window). Auth is the abuse-sensitive surface (07 §4).
RATE_LIMITS: dict[str, str] = {
    "register": "5/minute",
    "login": "10/minute",
    "refresh": "30/minute",
}


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    """Return the standard envelope for a 429 and attach ``Retry-After`` via slowapi.

    ``exc`` is typed ``Exception`` to satisfy Starlette's ``add_exception_handler`` signature
    (it is always a ``RateLimitExceeded`` here); its detail isn't needed — the envelope is generic.
    """
    response: Response = JSONResponse(
        status_code=429,
        content=jsonable_encoder(Envelope.fail("rate_limited", "too many requests")),
    )
    # slowapi computes Retry-After + X-RateLimit-* from the breached window.
    return limiter._inject_headers(response, request.state.view_rate_limit)


__all__ = ["RATE_LIMITS", "limiter", "rate_limit_exceeded_handler"]

"""Request-context middleware for the API role.

Binds a per-request correlation id (and the active trace ids) so structlog can stamp
every log line, echoes ``X-Request-ID`` on the response, and injects ``meta.request_id``
into success envelopes (``plans/08 §6``: trace ids in logs *and* responses). Existing
``meta`` (e.g. ``next_cursor``) is merged, never clobbered; error envelopes keep their
canonical ``{success:false,data:null,error}`` shape (only the header is added).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from quantvista.core.observability.context import bind_correlation, clear_correlation
from quantvista.core.observability.tracing import current_trace_ids

REQUEST_ID_HEADER = "X-Request-ID"

# A client may supply its own correlation id, but we only trust a bounded, safe token
# (no newlines/control chars → no log injection; capped length → no log/response bloat).
# Anything else is replaced with a server-generated UUID.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_Call = Callable[[Request], Awaitable[Response]]


def _safe_request_id(raw: str | None) -> str:
    return raw if raw and _SAFE_REQUEST_ID.match(raw) else str(uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind correlation, echo the request id, and enrich success envelopes."""

    async def dispatch(self, request: Request, call_next: _Call) -> Response:
        request_id = _safe_request_id(request.headers.get(REQUEST_ID_HEADER))
        trace_id, span_id = current_trace_ids()
        bind_correlation(request_id, trace_id=trace_id, span_id=span_id)
        try:
            response = await call_next(request)
            response = await _inject_request_id(response, request_id)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            clear_correlation()


async def _inject_request_id(response: Response, request_id: str) -> Response:
    """Add ``meta.request_id`` to a success JSON envelope, rebuilding the body."""
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        return response

    body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
    payload = _try_load_envelope(body)
    if payload is not None and payload.get("success") is True:
        meta = payload.get("meta")
        meta = dict(meta) if isinstance(meta, dict) else {}
        meta.setdefault("request_id", request_id)
        payload["meta"] = meta
        body = json.dumps(payload).encode()

    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type="application/json",
    )


def _try_load_envelope(body: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) and "success" in payload else None

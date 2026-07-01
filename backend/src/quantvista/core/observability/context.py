"""Correlation context shared by logs, traces, and the response envelope.

A single request/task carries a ``request_id`` (and, when a trace is active, the
``trace_id``/``span_id``). These are stashed in context-locals so that:

- structlog can merge them onto every log line (via ``structlog.contextvars``), and
- the API layer can echo ``request_id`` back in ``meta.request_id`` + the response header.

``core`` is the foundation layer — this module imports no bounded context.
"""

from __future__ import annotations

from contextvars import ContextVar

import structlog

# Dedicated holder for the request id so the (non-logging) envelope layer can read it
# back without depending on structlog's contextvars internals.
_request_id: ContextVar[str | None] = ContextVar("qv_request_id", default=None)


def bind_correlation(
    request_id: str,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
) -> None:
    """Bind correlation ids for the current context (request or task).

    ``request_id`` is always bound; ``trace_id``/``span_id`` only when present (i.e. a
    trace is active). All bound fields are merged onto structlog log records.
    """
    _request_id.set(request_id)
    fields: dict[str, str] = {"request_id": request_id}
    if trace_id is not None:
        fields["trace_id"] = trace_id
    if span_id is not None:
        fields["span_id"] = span_id
    structlog.contextvars.bind_contextvars(**fields)


def get_request_id() -> str | None:
    """Return the current request id, or ``None`` outside a bound context."""
    return _request_id.get()


def clear_correlation() -> None:
    """Reset all correlation state (call at the end of a request/task)."""
    _request_id.set(None)
    structlog.contextvars.clear_contextvars()

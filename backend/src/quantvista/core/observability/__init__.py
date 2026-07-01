"""Observability foundation (QV-009): logging, tracing, metrics, error tracking.

Single-sourced across the ``api`` and ``worker`` roles (project rule: same image, three
roles — no forked logic). Every backend is env-driven and no-op-safe: a missing OTLP
endpoint, Sentry DSN, or ``metrics_enabled=false`` degrades gracefully rather than
crashing. ``core`` imports no bounded context, keeping the import-linter DAG intact.

``configure_observability(role, app=...)`` wires the three always-on concerns (structured
logging, tracing, Sentry) for a role; role-specific bits (API request/metrics middleware,
the worker metrics server) are attached by each composition root using the helpers below.
"""

from __future__ import annotations

from quantvista.core.observability import context
from quantvista.core.observability.logging import configure_logging
from quantvista.core.observability.sentry import configure_sentry
from quantvista.core.observability.tracing import (
    configure_tracing,
    instrument_celery,
    instrument_fastapi,
)

__all__ = [
    "configure_observability",
    "context",
    "configure_logging",
    "configure_tracing",
    "configure_sentry",
    "instrument_celery",
    "instrument_fastapi",
]


def configure_observability(role: str, *, app: object | None = None) -> None:
    """Wire logging + tracing + Sentry for ``role``; instrument a FastAPI ``app`` if given."""
    configure_logging(role)
    configure_tracing(role)
    configure_sentry(role)
    if app is not None:
        instrument_fastapi(app)

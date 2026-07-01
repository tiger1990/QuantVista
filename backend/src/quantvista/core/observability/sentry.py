"""Sentry error tracking for the api and worker roles.

Fully env-gated: with no ``sentry_dsn`` the SDK is never initialised, so local, CI, and the
no-creds dev box run untouched. When a DSN is present we init with strong PII controls:
``send_default_pii=False`` (drops cookies/IP/auth headers), ``max_request_body_size="never"``
(request bodies — e.g. login/refresh payloads — are never captured), and a ``before_send``
scrubber that strips any residual request data / cookies / breadcrumb data as defence in depth.
"""

from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.types import Event, Hint

from quantvista.core.config import get_settings


def _scrub_event(event: Event, _hint: Hint) -> Event:
    """Belt-and-suspenders: drop request bodies/cookies and breadcrumb data before send."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
    breadcrumbs = event.get("breadcrumbs")
    values = breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else None
    if isinstance(values, list):
        for crumb in values:
            if isinstance(crumb, dict):
                crumb.pop("data", None)
    return event


def configure_sentry(role: str) -> bool:
    """Initialise Sentry for ``role`` if a DSN is configured. Returns whether it inited."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_scrub_event,
        integrations=_integrations_for(role),
    )
    sentry_sdk.set_tag("role", role)
    return True


def _integrations_for(role: str) -> list[Any]:
    if role == "worker":
        from sentry_sdk.integrations.celery import CeleryIntegration

        return [CeleryIntegration()]
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    return [StarletteIntegration(), FastApiIntegration()]

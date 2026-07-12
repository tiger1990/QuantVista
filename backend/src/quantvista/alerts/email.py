"""Email sender seam (QV-049) — plug-and-play provider.

``IEmailSender`` is the interface; ``get_email_sender`` picks the concrete one from config
(``EMAIL_PROVIDER``). ``log`` (dev/CI, no creds) → ``LogEmailSender``; ``brevo`` → Brevo's
transactional REST API (300/day free). Adding Amazon SES later is a new class + one factory branch —
nothing else changes. HTTP uses stdlib ``urllib`` (the project's runtime HTTP, like the news
providers); a non-2xx raises so the caller marks the event ``failed`` and retries it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol

import structlog

from quantvista.core.config import Settings, get_settings

_log = structlog.get_logger()
_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class IEmailSender(Protocol):
    """Sends one email. Raises on failure (the delivery service records status per event)."""

    def send(self, *, to: str, subject: str, body: str) -> None: ...


class LogEmailSender:
    """Dev/CI sender — logs instead of sending (no provider creds). Never raises."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        _log.info("email_send_logged", to=to, subject=subject)


class BrevoEmailSender:
    """Brevo transactional email via its REST API (``api-key`` header). Raises on non-2xx."""

    def __init__(
        self, *, api_key: str, from_email: str, from_name: str, timeout: float = 10.0
    ) -> None:
        self._api_key = api_key
        self._sender = {"email": from_email, "name": from_name}
        self._timeout = timeout

    def send(self, *, to: str, subject: str, body: str) -> None:
        payload = json.dumps(
            {
                "sender": self._sender,
                "to": [{"email": to}],
                "subject": subject,
                "htmlContent": f"<p>{body}</p>",
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed https Brevo endpoint
            _BREVO_URL,
            data=payload,
            method="POST",
            headers={
                "api-key": self._api_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:  # noqa: S310
                if resp.status not in (200, 201):
                    raise RuntimeError(f"Brevo send failed: HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            raise RuntimeError(f"Brevo send failed: HTTP {exc.code} {detail}") from exc


def get_email_sender(settings: Settings | None = None) -> IEmailSender:
    """Build the configured email sender (``EMAIL_PROVIDER``); defaults to the log sender."""
    settings = settings or get_settings()
    provider = settings.email_provider.strip().casefold()
    if provider == "log":
        return LogEmailSender()
    if provider == "brevo":
        if not settings.brevo_api_key:
            raise RuntimeError("EMAIL_PROVIDER=brevo requires BREVO_API_KEY")
        return BrevoEmailSender(
            api_key=settings.brevo_api_key,
            from_email=settings.email_from,
            from_name=settings.email_from_name,
        )
    raise RuntimeError(f"unknown email_provider: {settings.email_provider!r} (want log|brevo)")

"""Unit tests for the email provider seam + factory (QV-049) — no network."""

from __future__ import annotations

import json
from typing import Any

import pytest

from quantvista.alerts.email import (
    BrevoEmailSender,
    LogEmailSender,
    get_email_sender,
)
from quantvista.core.config import Settings


def test_factory_defaults_to_log() -> None:
    assert isinstance(get_email_sender(Settings(email_provider="log")), LogEmailSender)


def test_factory_builds_brevo() -> None:
    sender = get_email_sender(
        Settings(email_provider="brevo", brevo_api_key="xkeysib-test", email_from="a@b.com")
    )
    assert isinstance(sender, BrevoEmailSender)


def test_factory_brevo_requires_key() -> None:
    with pytest.raises(RuntimeError, match="BREVO_API_KEY"):
        get_email_sender(Settings(email_provider="brevo", brevo_api_key=None))


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(RuntimeError, match="unknown email_provider"):
        get_email_sender(Settings(email_provider="mailgun"))


def test_brevo_posts_expected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Resp:
        status = 201

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    def _fake_urlopen(request: Any, timeout: float, context: Any = None) -> _Resp:
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = json.loads(request.data)
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    BrevoEmailSender(api_key="xkeysib-k", from_email="alerts@qv.com", from_name="QV").send(
        to="user@gmail.com", subject="Hi", body="an alert fired"
    )
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["headers"]["api-key"] == "xkeysib-k"
    assert captured["body"]["sender"] == {"email": "alerts@qv.com", "name": "QV"}
    assert captured["body"]["to"] == [{"email": "user@gmail.com"}]
    assert captured["body"]["subject"] == "Hi"


def test_brevo_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def _boom(request: Any, timeout: float, context: Any = None) -> None:
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(RuntimeError, match="Brevo send failed: HTTP 401"):
        BrevoEmailSender(api_key="bad", from_email="a@b.com", from_name="QV").send(
            to="u@g.com", subject="s", body="b"
        )

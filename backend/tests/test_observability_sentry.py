"""Unit tests for env-gated Sentry init (core.observability.sentry)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk

from quantvista.core.config import get_settings
from quantvista.core.observability import sentry


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_noop_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    # Act — no DSN configured
    inited = sentry.configure_sentry("api")
    # Assert — SDK never touched
    assert inited is False
    assert calls == []


def test_inits_with_dsn_and_no_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.5")
    monkeypatch.setenv("APP_ENV", "staging")
    get_settings.cache_clear()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a, **k: None)
    # Act
    inited = sentry.configure_sentry("api")
    # Assert
    assert inited is True
    (kwargs,) = calls
    assert kwargs["dsn"] == "https://public@sentry.example/1"
    assert kwargs["environment"] == "staging"
    assert kwargs["traces_sample_rate"] == 0.5
    assert kwargs["send_default_pii"] is False
    # PII controls: request bodies (login/refresh payloads) are never captured, and a
    # before_send scrubber strips residual request data / cookies / breadcrumbs.
    assert kwargs["max_request_body_size"] == "never"
    assert callable(kwargs["before_send"])
    assert kwargs["integrations"]  # role-appropriate integrations attached


def test_before_send_scrubs_request_body_and_cookies() -> None:
    # Arrange — an event as sentry would build it, carrying a login body + cookies.
    # (Typed Any to mirror sentry's runtime Event dict shape.)
    event: Any = {
        "request": {"data": {"password": "hunter2"}, "cookies": "qv_refresh=abc"},
        "breadcrumbs": {"values": [{"data": {"token": "leak"}}]},
    }
    # Act
    scrubbed: Any = sentry._scrub_event(event, {})
    # Assert — no request body / cookies / breadcrumb data survive
    assert "data" not in scrubbed["request"]
    assert "cookies" not in scrubbed["request"]
    assert "data" not in scrubbed["breadcrumbs"]["values"][0]

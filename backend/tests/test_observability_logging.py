"""Unit tests for structured logging + PII redaction (core.observability.logging)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

from quantvista.core.config import get_settings
from quantvista.core.observability import context
from quantvista.core.observability.logging import (
    configure_logging,
    redact_pii,
    sanitize_exc_info,
)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    get_settings.cache_clear()
    context.clear_correlation()
    yield
    get_settings.cache_clear()
    context.clear_correlation()
    structlog.reset_defaults()


def _redact(event: dict[str, Any]) -> dict[str, Any]:
    # structlog processor signature: (logger, method_name, event_dict)
    return dict(redact_pii(None, "info", event))


def test_redact_masks_each_sensitive_key() -> None:
    # Arrange
    event = {
        "password": "hunter2",
        "token": "abc",
        "authorization": "Bearer x",
        "cookie": "sid=1",
        "set-cookie": "sid=1",
        "secret": "s",
        "refresh": "r",
        "jwt": "j",
        "api_key": "k",
    }
    # Act
    out = _redact(dict(event))
    # Assert — every sensitive value masked, none leak
    for key in event:
        assert out[key] == "***redacted***", key


def test_redact_is_case_insensitive() -> None:
    # Arrange / Act
    out = _redact({"Authorization": "Bearer x", "PASSWORD": "p"})
    # Assert
    assert out["Authorization"] == "***redacted***"
    assert out["PASSWORD"] == "***redacted***"


def test_redact_masks_email_value() -> None:
    # Arrange / Act
    out = _redact({"email": "alice@example.com"})
    # Assert — local part masked but domain kept for debugging
    assert out["email"] == "a***@example.com"


def test_redact_leaves_safe_fields_untouched() -> None:
    # Arrange / Act
    out = _redact({"event": "login", "user_id": "u-1", "status": 200})
    # Assert
    assert out == {"event": "login", "user_id": "u-1", "status": 200}


def test_redact_catches_substring_and_variant_keys() -> None:
    # Arrange — keys not in any exact list but clearly sensitive
    out = _redact(
        {
            "set-cookie": "sid=1",
            "x-api-key": "k",
            "client_secret": "cs",
            "new_password": "p",
            "user_access_token": "t",
        }
    )
    # Assert
    assert all(v == "***redacted***" for v in out.values())


def test_redact_does_not_over_mask_legit_key_fields() -> None:
    # Arrange — job/diagnostic fields that merely contain "key" must survive (they are
    # explicitly logged per project-context: run_key on every job run).
    out = _redact({"run_key": "prices:NSE:2026-06-13", "cache_key": "c", "sort_key": "s"})
    # Assert
    assert out == {"run_key": "prices:NSE:2026-06-13", "cache_key": "c", "sort_key": "s"}


def test_redact_walks_nested_dicts() -> None:
    # Arrange — a raw header dict passed as a keyword value
    out = _redact({"headers": {"authorization": "Bearer x", "x-request-id": "ok"}})
    # Assert — nested secret masked, benign nested field preserved
    assert out["headers"]["authorization"] == "***redacted***"
    assert out["headers"]["x-request-id"] == "ok"


def test_sanitize_exc_info_scrubs_credentials_in_traceback() -> None:
    # Arrange — a rendered traceback string carrying secrets in several shapes
    tb = (
        "ValueError: auth failed token=eyJabc.def.ghi\n"
        "  conn=postgresql://user:s3cr3t@db:5432/x\n"
        "  header: Bearer abc123DEF"
    )
    # Act
    out = sanitize_exc_info(None, "error", {"exc_info": tb})
    text = out["exc_info"]
    # Assert — none of the secret material survives
    assert "eyJabc.def.ghi" not in text
    assert "s3cr3t" not in text
    assert "abc123DEF" not in text
    assert "***redacted***" in text


def test_configure_logging_emits_json_with_correlation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    monkeypatch.setenv("LOG_JSON", "true")
    get_settings.cache_clear()
    configure_logging("api")
    context.bind_correlation(request_id="req-9", trace_id="t-9", span_id="s-9")
    log = structlog.get_logger()
    # Act — a sensitive field must not survive to the rendered line
    log.info("user_login", user_id="u-1", password="hunter2")
    captured = capsys.readouterr().out.strip()
    # Assert — valid JSON with correlation + role + level + redaction
    record = json.loads(captured)
    assert record["event"] == "user_login"
    assert record["level"] == "info"
    assert record["role"] == "api"
    assert record["request_id"] == "req-9"
    assert record["trace_id"] == "t-9"
    assert record["span_id"] == "s-9"
    assert "timestamp" in record
    assert record["password"] == "***redacted***"
    assert "hunter2" not in captured

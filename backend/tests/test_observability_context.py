"""Unit tests for the correlation context helpers (core.observability.context)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog

from quantvista.core.observability import context


@pytest.fixture(autouse=True)
def _clear_context() -> Iterator[None]:
    context.clear_correlation()
    yield
    context.clear_correlation()


def test_request_id_absent_by_default() -> None:
    # Arrange / Act / Assert
    assert context.get_request_id() is None


def test_bind_sets_request_id_and_structlog_contextvars() -> None:
    # Arrange / Act
    context.bind_correlation(request_id="req-1", trace_id="t-1", span_id="s-1")
    # Assert — request id readable for the envelope layer
    assert context.get_request_id() == "req-1"
    # Assert — all fields merged into structlog's contextvars for log correlation
    merged = structlog.contextvars.get_contextvars()
    assert merged["request_id"] == "req-1"
    assert merged["trace_id"] == "t-1"
    assert merged["span_id"] == "s-1"


def test_bind_omits_absent_trace_and_span() -> None:
    # Arrange / Act — no active span → only request_id bound
    context.bind_correlation(request_id="req-2")
    # Assert
    merged = structlog.contextvars.get_contextvars()
    assert merged["request_id"] == "req-2"
    assert "trace_id" not in merged
    assert "span_id" not in merged


def test_clear_removes_all_correlation() -> None:
    # Arrange
    context.bind_correlation(request_id="req-3", trace_id="t-3")
    # Act
    context.clear_correlation()
    # Assert
    assert context.get_request_id() is None
    assert structlog.contextvars.get_contextvars() == {}

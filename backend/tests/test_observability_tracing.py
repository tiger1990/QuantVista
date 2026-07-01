"""Unit tests for OpenTelemetry tracing wiring (core.observability.tracing)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider

from quantvista.core.config import get_settings
from quantvista.core.observability import tracing


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_configure_tracing_sets_service_resource() -> None:
    # Arrange / Act
    provider = tracing.configure_tracing("api")
    # Assert — resource identifies this role + environment
    attrs = provider.resource.attributes
    assert attrs["service.name"] == "quantvista-api"
    assert attrs["deployment.environment"] == "local"


def test_configure_tracing_respects_service_name_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-svc")
    get_settings.cache_clear()
    # Act
    provider = tracing.configure_tracing("worker")
    # Assert
    assert provider.resource.attributes["service.name"] == "custom-svc"


def test_no_otlp_exporter_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — record whether the exporter is ever constructed
    calls: list[str] = []

    def _fake_exporter(**kw: object) -> object:
        calls.append(str(kw.get("endpoint", "")))
        return object()

    monkeypatch.setattr(tracing, "OTLPSpanExporter", _fake_exporter)
    # Act — no endpoint configured
    tracing.configure_tracing("api")
    # Assert — never build an exporter without a collector to point at
    assert calls == []


def test_otlp_exporter_built_when_endpoint_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    get_settings.cache_clear()
    endpoints: list[str] = []

    def _fake_exporter(**kw: object) -> object:
        endpoints.append(str(kw["endpoint"]))
        return object()

    added: list[object] = []
    monkeypatch.setattr(tracing, "OTLPSpanExporter", _fake_exporter)
    monkeypatch.setattr(TracerProvider, "add_span_processor", lambda self, p: added.append(p))
    # Act
    tracing.configure_tracing("api")
    # Assert
    assert endpoints == ["http://collector:4317"]
    assert len(added) == 1


def test_current_trace_ids_none_without_active_span() -> None:
    # Arrange / Act / Assert
    assert tracing.current_trace_ids() == (None, None)


def test_current_trace_ids_returns_hex_within_span() -> None:
    # Arrange
    provider = tracing.configure_tracing("api")
    tracer = provider.get_tracer("test")
    # Act
    with tracer.start_as_current_span("op"):
        trace_id, span_id = tracing.current_trace_ids()
    # Assert — 128-bit trace id / 64-bit span id, lowercase hex
    assert trace_id is not None and len(trace_id) == 32
    assert span_id is not None and len(span_id) == 16

"""OpenTelemetry tracing for the api and worker roles.

Builds a ``TracerProvider`` tagged with ``service.name``/``deployment.environment`` and,
**only when ``otel_exporter_otlp_endpoint`` is set**, ships spans via OTLP. With no
endpoint the provider is installed without an exporter: spans are created (so trace ids
still correlate logs and the envelope) but nothing is shipped — the app never blocks on a
missing collector. Instrumentation of FastAPI/Celery is applied at the composition roots.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from quantvista.core.config import get_settings


def configure_tracing(role: str) -> TracerProvider:
    """Create + install a ``TracerProvider`` for ``role``; return it for wiring/tests."""
    settings = get_settings()
    service_name = settings.otel_service_name or f"quantvista-{role}"
    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": settings.app_env,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    # Global provider is set-once per process; only claim it if still the default proxy.
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(provider)
    return provider


def instrument_fastapi(app: Any) -> None:
    """Attach OTel request spans to a FastAPI app (composition root only)."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def instrument_celery() -> None:
    """Attach OTel task spans to Celery (worker composition root only)."""
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    # OTel contrib ships no py.typed marker, so this constructor is untyped under strict.
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]


def current_trace_ids() -> tuple[str | None, str | None]:
    """Return ``(trace_id, span_id)`` as lowercase hex for the active span, else Nones."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return format(span_context.trace_id, "032x"), format(span_context.span_id, "016x")

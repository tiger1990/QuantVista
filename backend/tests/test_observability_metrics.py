"""Unit tests for Prometheus metrics (core.observability.metrics)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY
from starlette.responses import PlainTextResponse

from quantvista.core.observability import metrics


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(metrics.PrometheusMiddleware)

    @app.get("/things/{tid}")
    def things(tid: str) -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/broken")
    def broken() -> PlainTextResponse:
        return PlainTextResponse("boom", status_code=500)

    @app.get("/raises")
    def raises() -> PlainTextResponse:
        raise RuntimeError("kaboom")

    @app.get(metrics.METRICS_PATH)
    def metrics_endpoint() -> PlainTextResponse:
        payload, content_type = metrics.render_metrics()
        return PlainTextResponse(payload, media_type=content_type)

    return app


def test_metrics_endpoint_serves_prometheus_text() -> None:
    # Arrange
    client = TestClient(_app())
    # Act
    resp = client.get(metrics.METRICS_PATH)
    # Assert — content type is the library's canonical Prometheus exposition type
    # (prometheus-client 0.25 emits version=1.0.0; assert against the source of truth).
    assert resp.status_code == 200
    assert resp.headers["content-type"] == CONTENT_TYPE_LATEST
    assert CONTENT_TYPE_LATEST.startswith("text/plain")
    assert "http_requests_total" in resp.text


def test_red_counter_uses_route_template_not_raw_path() -> None:
    # Arrange
    client = TestClient(_app())
    before = (
        REGISTRY.get_sample_value(
            "http_requests_total", {"method": "GET", "route": "/things/{tid}", "status": "200"}
        )
        or 0.0
    )
    # Act — two different concrete paths must fold into one route-template series
    client.get("/things/1")
    client.get("/things/2")
    after = REGISTRY.get_sample_value(
        "http_requests_total", {"method": "GET", "route": "/things/{tid}", "status": "200"}
    )
    # Assert
    assert after == before + 2


def test_latency_histogram_records_observations() -> None:
    # Arrange
    client = TestClient(_app())
    # Act
    client.get("/things/9")
    count = REGISTRY.get_sample_value(
        "http_request_duration_seconds_count", {"method": "GET", "route": "/things/{tid}"}
    )
    # Assert
    assert count is not None and count >= 1


def test_5xx_response_increments_error_counter() -> None:
    # Arrange
    client = TestClient(_app())
    before = (
        REGISTRY.get_sample_value(
            "http_request_errors_total", {"method": "GET", "route": "/broken"}
        )
        or 0.0
    )
    # Act
    client.get("/broken")
    after = REGISTRY.get_sample_value(
        "http_request_errors_total", {"method": "GET", "route": "/broken"}
    )
    # Assert — RED "errors" tracks server failures distinctly
    assert after == before + 1


def test_unhandled_exception_is_counted_as_error() -> None:
    # Arrange
    client = TestClient(_app(), raise_server_exceptions=True)
    before = (
        REGISTRY.get_sample_value(
            "http_request_errors_total", {"method": "GET", "route": "/raises"}
        )
        or 0.0
    )
    # Act — the handler raises; the middleware records a 500 then re-raises
    with pytest.raises(RuntimeError):
        client.get("/raises")
    after = REGISTRY.get_sample_value(
        "http_request_errors_total", {"method": "GET", "route": "/raises"}
    )
    # Assert
    assert after == before + 1


def test_worker_task_signals_record_metrics() -> None:
    # Arrange
    class _Task:
        name = "quantvista.demo"

    before = (
        REGISTRY.get_sample_value(
            "celery_tasks_total", {"task": "quantvista.demo", "state": "SUCCESS"}
        )
        or 0.0
    )
    # Act
    metrics.record_task_prerun(task_id="t-1")
    metrics.record_task_postrun(task_id="t-1", task=_Task(), state="SUCCESS")
    metrics.record_task_failure(sender=_Task())
    # Assert
    after = REGISTRY.get_sample_value(
        "celery_tasks_total", {"task": "quantvista.demo", "state": "SUCCESS"}
    )
    failures = REGISTRY.get_sample_value("celery_task_failures_total", {"task": "quantvista.demo"})
    latency_count = REGISTRY.get_sample_value(
        "celery_task_duration_seconds_count", {"task": "quantvista.demo"}
    )
    assert after == before + 1
    assert failures is not None and failures >= 1
    assert latency_count is not None and latency_count >= 1

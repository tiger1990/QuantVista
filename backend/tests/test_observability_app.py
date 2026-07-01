"""App-level integration: the wired API emits correlation + metrics end-to-end."""

from __future__ import annotations

from fastapi.testclient import TestClient

from quantvista.api.app import create_app
from quantvista.api.middleware import REQUEST_ID_HEADER


def test_health_carries_request_id_header_and_meta() -> None:
    # Arrange
    client = TestClient(create_app())
    # Act
    resp = client.get("/api/v1/health")
    # Assert — correlation surfaces in both the header and the envelope meta
    assert resp.status_code == 200
    request_id = resp.headers[REQUEST_ID_HEADER]
    assert request_id
    assert resp.json()["meta"]["request_id"] == request_id


def test_metrics_endpoint_reports_request_after_traffic() -> None:
    # Arrange
    client = TestClient(create_app())
    # Act — generate one request, then scrape
    client.get("/api/v1/health")
    resp = client.get("/metrics")
    # Assert — ops endpoint (outside /api/v1, no envelope) exposes RED series
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in resp.text
    assert "/api/v1/health" in resp.text


def test_metrics_endpoint_is_not_under_api_v1() -> None:
    # Arrange
    client = TestClient(create_app())
    # Act / Assert
    assert client.get("/api/v1/metrics").status_code == 404

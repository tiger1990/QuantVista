"""Tests for the api health endpoint (quantvista.api.app)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from quantvista.api.app import create_app


def test_health_returns_ok_envelope() -> None:
    # Arrange
    client = TestClient(create_app())
    # Act
    response = client.get("/api/v1/health")
    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {"status": "ok"}
    assert body["error"] is None


def test_health_is_under_api_v1() -> None:
    # Arrange
    client = TestClient(create_app())
    # Act / Assert — unversioned path is not mounted
    assert client.get("/health").status_code == 404

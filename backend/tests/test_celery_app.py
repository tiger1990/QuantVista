"""Tests for the Celery app wiring (quantvista.jobs.celery_app)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from quantvista.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_celery_app_uses_configured_redis_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/3")
    from quantvista.jobs.celery_app import create_celery

    # Act
    celery = create_celery()
    # Assert
    assert celery.conf.broker_url == "redis://example:6379/3"
    assert celery.conf.result_backend == "redis://example:6379/3"


def test_ping_task_registered_and_returns_pong() -> None:
    # Arrange / Act
    from quantvista.jobs.celery_app import app, ping

    # Assert
    assert "quantvista.ping" in app.tasks
    assert ping() == "pong"

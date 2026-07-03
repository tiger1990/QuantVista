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


def test_beat_schedule_and_retry_defaults_configured() -> None:
    # Arrange / Act
    from quantvista.jobs.celery_app import create_celery

    celery = create_celery()
    # Assert — Beat schedules the sample job root; fail-loud/retry-smart defaults set (06 §1.4)
    entry = celery.conf.beat_schedule["sample-heartbeat"]
    assert entry["task"] == "quantvista.sample_scheduled_job"
    assert celery.conf.task_acks_late is True
    assert celery.conf.task_reject_on_worker_lost is True


def test_sample_scheduled_job_registered() -> None:
    # Arrange / Act
    from quantvista.jobs.celery_app import app

    # Assert
    assert "quantvista.sample_scheduled_job" in app.tasks

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


def test_producer_and_worker_agree_on_task_routes() -> None:
    """Regression: Celery routes in the PRODUCER, so a worker-only routing table strands
    API-published tasks on the default queue (a submitted backtest sat in `celery` while
    `worker -Q user` idled). Both ends must read the one shared table."""
    # Arrange / Act
    from quantvista.core.tasks import TASK_DEFAULT_QUEUE, TASK_ROUTES, _producer, queue_for
    from quantvista.jobs.celery_app import create_celery

    worker = create_celery()
    producer = _producer()

    # Assert — same table, same default, on both sides of the broker
    assert producer.conf.task_routes == worker.conf.task_routes == TASK_ROUTES
    assert producer.conf.task_default_queue == worker.conf.task_default_queue == TASK_DEFAULT_QUEUE
    # the interactive backtest queue specifically (the one that broke)
    assert queue_for("quantvista.run_backtest") == "user"
    assert queue_for("quantvista.unrouted_task") == TASK_DEFAULT_QUEUE


def test_producer_publishes_backtest_to_the_user_queue() -> None:
    """The published message actually carries the `user` routing key — not just config equality."""
    # Arrange
    from quantvista.core.tasks import _producer

    producer = _producer()

    # Act — record the routing decision without touching a real broker
    with producer.connection_for_write() as conn:
        opts = producer.amqp.router.route({}, "quantvista.run_backtest", (), {}, conn)

    # Assert
    assert opts["queue"].name == "user"

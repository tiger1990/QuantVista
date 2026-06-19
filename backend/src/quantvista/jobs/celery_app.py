"""Celery application (the ``worker`` and ``beat`` runtime roles).

Broker and result backend are Redis (from ``Settings.redis_url``). Real jobs land from
QV-015+; QV-002 ships a single ``ping`` task to prove the worker processes jobs.
Discover with ``celery -A quantvista.jobs.celery_app worker`` (instance named ``app``).
"""

from __future__ import annotations

from celery import Celery

from quantvista.core.config import get_settings


def create_celery() -> Celery:
    settings = get_settings()
    celery = Celery(
        "quantvista",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    celery.conf.task_default_queue = "default"
    celery.conf.timezone = "UTC"
    return celery


app = create_celery()
celery_app = app  # alias for `-A quantvista.jobs.celery_app` discovery


@app.task(name="quantvista.ping")
def ping() -> str:
    """Trivial liveness task proving the worker is consuming the queue."""
    return "pong"

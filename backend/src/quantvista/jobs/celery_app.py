"""Celery application (the ``worker`` and ``beat`` runtime roles).

Broker and result backend are Redis (from ``Settings.redis_url``). Real jobs land from
QV-015+; QV-002 ships a single ``ping`` task to prove the worker processes jobs.
Discover with ``celery -A quantvista.jobs.celery_app worker`` (instance named ``app``).
"""

from __future__ import annotations

import contextlib

from celery import Celery
from celery.signals import worker_process_init

from quantvista.core.config import get_settings
from quantvista.core.observability import configure_observability, instrument_celery
from quantvista.core.observability.metrics import (
    install_worker_metrics,
    start_worker_metrics_server,
)


def create_celery() -> Celery:
    settings = get_settings()
    celery = Celery(
        "quantvista",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    celery.conf.task_default_queue = "default"
    celery.conf.timezone = "UTC"
    # Connect task metrics signals now (lightweight, no side effects / no ports). The
    # heavier per-process wiring runs in worker_process_init below.
    install_worker_metrics()
    return celery


@worker_process_init.connect
def _init_worker_observability(**_: object) -> None:
    """Wire logging/tracing/Sentry + start the metrics server inside a real worker only."""
    configure_observability("worker")
    instrument_celery()
    settings = get_settings()
    if settings.metrics_enabled:
        # Port already bound (e.g. multiple worker processes on one host) is fine — the
        # first server serves the shared registry; subsequent binds are safe to skip.
        with contextlib.suppress(OSError):
            start_worker_metrics_server(settings.worker_metrics_port)


app = create_celery()
celery_app = app  # alias for `-A quantvista.jobs.celery_app` discovery


@app.task(name="quantvista.ping")
def ping() -> str:
    """Trivial liveness task proving the worker is consuming the queue."""
    return "pong"

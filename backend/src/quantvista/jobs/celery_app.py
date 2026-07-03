"""Celery application (the ``worker`` and ``beat`` runtime roles).

Broker and result backend are Redis (from ``Settings.redis_url``). The QV-015 job framework
(``run_key`` + ``JobRunLedger`` + ``run_job``) lands here; Beat schedules the *roots* of each
DAG (``06`` §1.2) — for now a single ``sample_scheduled_job`` proves the path end-to-end.
Discover with ``celery -A quantvista.jobs.celery_app worker`` (instance named ``app``).
"""

from __future__ import annotations

import contextlib
from datetime import date

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from quantvista.core.config import get_settings
from quantvista.core.observability import configure_observability, instrument_celery
from quantvista.core.observability.metrics import (
    install_worker_metrics,
    start_worker_metrics_server,
)
from quantvista.jobs.framework import JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger

SAMPLE_JOB_NAME = "sample_scheduled_job"

# Beat schedules only the roots of each DAG (06 §1.2). Cadence is IST-intent but Celery runs
# in UTC (timezone below); real ingestion schedules land with QV-016+.
BEAT_SCHEDULE = {
    "sample-heartbeat": {
        "task": "quantvista.sample_scheduled_job",
        "schedule": crontab(minute=0, hour=1),  # daily tick — placeholder cadence
    },
    # Ops-metrics refresh: cheap internal gauges (freshness + queue depth). Unlike data jobs
    # (which stay off Beat until a real feed/staging), this IS the thing we schedule (QV-020).
    "refresh-ops-metrics": {
        "task": "quantvista.refresh_ops_metrics",
        "schedule": 60.0,  # seconds
    },
}


def create_celery() -> Celery:
    settings = get_settings()
    celery = Celery(
        "quantvista",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["quantvista.jobs.ops_metrics"],  # register the Beat-scheduled ops task
    )
    celery.conf.task_default_queue = "default"
    celery.conf.timezone = "UTC"
    celery.conf.beat_schedule = BEAT_SCHEDULE
    # Fail-loud / retry-smart defaults (06 §1.4): re-deliver on worker loss; per-task
    # autoretry uses exponential backoff + jitter (see the sample task).
    celery.conf.task_acks_late = True
    celery.conf.task_reject_on_worker_lost = True
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


@app.task(
    name="quantvista.sample_scheduled_job",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def sample_scheduled_job(key: str | None = None) -> str:
    """Beat-scheduled sample job: runs the full ledger lifecycle end-to-end.

    Proves run_key + JobRunLedger + run_job (idempotent, recorded in ``jobs_runs``). Beat
    calls it with no args (a per-day key → idempotent per day); tests pass an explicit key.
    """
    resolved = key or run_key("sample", date.today().isoformat())
    outcome = run_job(
        SAMPLE_JOB_NAME, resolved, lambda: JobResult(rows_in=0, rows_out=0), ledger=JobRunLedger()
    )
    return outcome.status.value

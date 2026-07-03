"""Ops-metrics refresh (QV-020) — keep the pipeline-health gauges current.

The freshness + queue-depth gauges live on the Prometheus default registry (``core.observability
.metrics``); these updaters query the DB / Redis and set them, and a small Beat task refreshes them
so scrapes always see fresh values. DB/Redis I/O lives here (a composition root), not in ``core``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from quantvista.core.db import privileged_session_scope
from quantvista.core.observability.metrics import set_data_freshness, set_queue_depth
from quantvista.jobs.celery_app import app
from quantvista.market_data.repositories import latest_price_date

_FRESHNESS_DATASET = "daily_prices"
_DEFAULT_QUEUES = ("default",)


def update_data_freshness(session: Session, dataset: str = _FRESHNESS_DATASET) -> float | None:
    """Set the freshness gauge to the newest ingested date (as a UTC epoch); skip if empty."""
    latest = latest_price_date(session)
    if latest is None:
        return None  # no data yet — do not publish a fake 0 (would read as 1970 / infinitely stale)
    ts = datetime(latest.year, latest.month, latest.day, tzinfo=UTC).timestamp()
    set_data_freshness(dataset, ts)
    return ts


def update_queue_depth(
    redis_client: Any, queues: tuple[str, ...] = _DEFAULT_QUEUES
) -> dict[str, int]:
    """Set the queue-depth gauge from each queue's Redis ``LLEN``. Returns the observed depths."""
    depths: dict[str, int] = {}
    for queue in queues:
        depth = int(redis_client.llen(queue))
        set_queue_depth(queue, depth)
        depths[queue] = depth
    return depths


@app.task(name="quantvista.refresh_ops_metrics")
def refresh_ops_metrics() -> str:
    """Refresh the freshness + queue-depth gauges (Beat-scheduled; cheap, no data mutation)."""
    import redis

    from quantvista.core.config import get_settings

    with privileged_session_scope() as session:
        update_data_freshness(session)
    client = redis.Redis.from_url(get_settings().redis_url)
    update_queue_depth(client)
    return "ok"

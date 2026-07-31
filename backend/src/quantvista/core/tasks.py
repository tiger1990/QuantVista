"""Task producer seam (QV-062).

Lets a composition root (``api``) enqueue a Celery task **by name** without importing the ``jobs``
worker app — the DAG makes ``api`` and ``jobs`` independent sibling composition roots (neither may
import the other). The worker (``jobs.celery_app``) registers the task under the same name;
``send_task`` routes by name through the broker. ``core`` may import the third-party ``celery``
(foundation-purity forbids only domain contexts, not libraries).

**Routing lives here, not only on the worker.** Celery applies ``task_routes`` in the *producer*
at publish time, so a producer without the table publishes to the default queue regardless of what
the worker declares. The API would then drop ``run_backtest`` into ``celery`` while a
``worker -Q user`` waits forever. ``jobs.celery_app`` imports this same table (``jobs`` may import
``core``; the reverse is forbidden) so both ends agree by construction.
"""

from __future__ import annotations

from functools import lru_cache

from celery import Celery

from quantvista.core.config import get_settings

# Dedicated queues keep interactive/heavy work off the data pipeline (06 §4): `nlp` for pluggable
# sentiment inference (QV-044), `user` for long-running interactive backtests (QV-065), `compute`
# for the Parquet export (QV-067). Everything else rides the default queue.
TASK_DEFAULT_QUEUE = "default"
TASK_ROUTES: dict[str, dict[str, str]] = {
    "quantvista.score_news": {"queue": "nlp"},
    "quantvista.run_backtest": {"queue": "user"},
    "quantvista.export_prices_parquet": {"queue": "compute"},
}


@lru_cache
def _producer() -> Celery:
    """A publish-only Celery client (broker only) — distinct from the worker app in ``jobs``."""
    celery = Celery("quantvista-producer", broker=get_settings().redis_url)
    celery.conf.task_default_queue = TASK_DEFAULT_QUEUE
    celery.conf.task_routes = TASK_ROUTES
    return celery


def queue_for(task_name: str) -> str:
    """The queue ``task_name`` publishes to — the routing table, with the default as fallback."""
    return TASK_ROUTES.get(task_name, {}).get("queue", TASK_DEFAULT_QUEUE)


def enqueue(task_name: str, *args: object) -> None:
    """Publish ``task_name`` with ``args`` to the broker for a worker to run."""
    _producer().send_task(task_name, args=list(args))


__all__ = ["TASK_DEFAULT_QUEUE", "TASK_ROUTES", "enqueue", "queue_for"]

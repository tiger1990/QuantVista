"""Task producer seam (QV-062).

Lets a composition root (``api``) enqueue a Celery task **by name** without importing the ``jobs``
worker app — the DAG makes ``api`` and ``jobs`` independent sibling composition roots (neither may
import the other). The worker (``jobs.celery_app``) registers the task under the same name;
``send_task`` routes by name through the broker. ``core`` may import the third-party ``celery``
(foundation-purity forbids only domain contexts, not libraries).
"""

from __future__ import annotations

from functools import lru_cache

from celery import Celery

from quantvista.core.config import get_settings


@lru_cache
def _producer() -> Celery:
    """A publish-only Celery client (broker only) — distinct from the worker app in ``jobs``."""
    return Celery("quantvista-producer", broker=get_settings().redis_url)


def enqueue(task_name: str, *args: object) -> None:
    """Publish ``task_name`` with ``args`` to the broker for a worker to run."""
    _producer().send_task(task_name, args=list(args))


__all__ = ["enqueue"]

"""refresh_ops_metrics task wiring (QV-020) — real Postgres, fake Redis (no live broker).

The task refreshes the freshness + queue-depth gauges. It queries daily_prices via a privileged
session (real DB) and Redis via a client we monkeypatch, so no broker is needed. The beat schedule
carries the task; here we prove the task body runs end-to-end and is registered.
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from quantvista.jobs import ops_metrics
from quantvista.jobs.celery_app import app

pytestmark = pytest.mark.integration


class _FakeRedis:
    def llen(self, key: str) -> int:
        return 3


def test_refresh_ops_metrics_task_runs_and_sets_queue_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis

    # Patch only Redis.from_url (not the whole module — Celery imports from redis too).
    monkeypatch.setattr(redis.Redis, "from_url", lambda url: _FakeRedis())
    result = ops_metrics.refresh_ops_metrics.apply()
    assert result.get() == "ok"
    assert REGISTRY.get_sample_value("celery_queue_depth", {"queue": "default"}) == 3.0


def test_refresh_ops_metrics_is_registered_and_beat_scheduled() -> None:
    assert "quantvista.refresh_ops_metrics" in app.tasks
    assert "refresh-ops-metrics" in app.conf.beat_schedule

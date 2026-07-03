"""Unit tests for the ops metrics updaters (freshness + queue depth), QV-020.

The gauges live on the default Prometheus registry; the updaters query a DB session / Redis and
set them. Fakes keep this network-free and deterministic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from prometheus_client import REGISTRY

from quantvista.jobs.ops_metrics import update_data_freshness, update_queue_depth


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value


class _FakeSession:
    def __init__(self, latest: date | None) -> None:
        self._latest = latest

    def execute(self, *_: Any, **__: Any) -> _FakeResult:
        return _FakeResult(self._latest)


class _FakeRedis:
    def __init__(self, depths: dict[str, int]) -> None:
        self._depths = depths

    def llen(self, key: str) -> int:
        return self._depths.get(key, 0)


def test_freshness_gauge_is_set_to_latest_date_epoch() -> None:
    latest = date(2026, 6, 30)
    ts = update_data_freshness(_FakeSession(latest))  # type: ignore[arg-type]
    expected = datetime(2026, 6, 30, tzinfo=UTC).timestamp()
    assert ts == expected
    assert (
        REGISTRY.get_sample_value(
            "data_latest_ingest_timestamp_seconds", {"dataset": "daily_prices"}
        )
        == expected
    )


def test_freshness_is_skipped_when_no_data() -> None:
    # An empty table must not publish a fake 0 (which would read as "1970 — infinitely stale").
    assert update_data_freshness(_FakeSession(None)) is None  # type: ignore[arg-type]


def test_queue_depth_gauge_is_set_from_redis_llen() -> None:
    depths = update_queue_depth(_FakeRedis({"default": 7}), queues=("default",))
    assert depths == {"default": 7}
    assert REGISTRY.get_sample_value("celery_queue_depth", {"queue": "default"}) == 7.0

"""RedisCache integration (QV-031) — real Redis (CI has the redis:7 service; local native Redis).

Round-trip JSON values, delete, TTL expiry, and the end-to-end ScoresComputed → cache invalidation
through the real client. Skips gracefully if Redis is unavailable. Unique keys, cleaned up.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import uuid4

import pytest

from quantvista.core.cache import RedisCache
from quantvista.core.config import get_settings
from quantvista.core.events import InProcessEventBus
from quantvista.jobs import consumers

pytestmark = pytest.mark.integration


@pytest.fixture
def cache() -> Iterator[tuple[RedisCache, list[str]]]:
    client = RedisCache(get_settings().redis_url)
    probe = f"qv:probe:{uuid4().hex}"
    try:
        client.set(probe, 1, ttl_seconds=5)
    except Exception as exc:  # redis absent / not importable → skip, don't fail
        pytest.skip(f"Redis unavailable: {exc}")
    keys: list[str] = [probe]
    yield client, keys
    client.delete(*keys)


def test_roundtrip_and_delete(cache: tuple[RedisCache, list[str]]) -> None:
    client, keys = cache
    key = f"rank:NSE:{uuid4().hex}"
    keys.append(key)
    payload = [
        {"symbol": "AAA", "composite_score": 73.2},
        {"symbol": "BBB", "composite_score": 10.6},
    ]
    client.set(key, payload, ttl_seconds=60)
    assert client.get(key) == payload  # JSON round-trip preserves the ranking
    client.delete(key)
    assert client.get(key) is None


def test_ttl_backstop_expires(cache: tuple[RedisCache, list[str]]) -> None:
    client, keys = cache
    key = f"rank:NSE:{uuid4().hex}"
    keys.append(key)
    client.set(key, [1, 2, 3], ttl_seconds=1)
    assert client.get(key) == [1, 2, 3]
    time.sleep(1.2)
    assert client.get(key) is None  # expired without any event


def test_scores_computed_invalidates_real_redis(
    cache: tuple[RedisCache, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, keys = cache
    market, day = "NSE", "2026-01-20"
    key = f"rank:{market}:{day}"
    keys.append(key)
    client.set(key, [{"symbol": "AAA"}], ttl_seconds=300)
    assert client.get(key) is not None

    monkeypatch.setattr(consumers, "get_cache", lambda: client)
    bus = InProcessEventBus()
    consumers.register_pipeline_consumers(bus)
    bus.publish(
        "ScoresComputed",
        {"universe": market, "date": day, "model_version": "score-v1", "count": 1},
    )
    assert client.get(key) is None  # invalidated through the real Redis client

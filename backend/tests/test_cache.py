"""Cache unit tests (QV-031) — NullCache, cache-aside read-through, invalidation consumer.

Fake in-memory cache + patched DB read → no Redis/Postgres. Pins: NullCache misses, cache-aside hits
skip the DB, and ScoresComputed invalidates the right keys.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from quantvista.analytics import services
from quantvista.core.cache import NullCache
from quantvista.core.events import InProcessEventBus
from quantvista.jobs import consumers
from quantvista.jobs.consumers import register_pipeline_consumers

_D = date(2026, 1, 20)


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.deleted: list[str] = []

    def get(self, key: str) -> Any | None:
        return self.store.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self.store[key] = value

    def delete(self, *keys: str) -> None:
        self.deleted.extend(keys)
        for k in keys:
            self.store.pop(k, None)


def test_null_cache_always_misses() -> None:
    cache = NullCache()
    cache.set("k", [1, 2], ttl_seconds=10)
    assert cache.get("k") is None
    cache.delete("k")  # no-op, no error


def test_cached_rankings_miss_populates_then_hit_skips_db(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, date]] = []

    def fake_read(session: object, market: str, as_of: date) -> list[dict[str, object]]:
        calls.append((market, as_of))
        return [{"symbol": "AAA", "composite_score": 50.0}]

    monkeypatch.setattr(services, "rankings_for", fake_read)
    cache = _FakeCache()
    first = services.cached_rankings(cache, cast(Session, None), "NSE", _D)  # miss → DB
    second = services.cached_rankings(cache, cast(Session, None), "NSE", _D)  # hit → no DB
    assert first == second == [{"symbol": "AAA", "composite_score": 50.0}]
    assert calls == [("NSE", _D)]  # DB read happened exactly once (the miss)
    assert cache.store["rank:NSE:2026-01-20"] == first  # populated under the ranking key


def test_scores_computed_invalidates_the_ranking_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _FakeCache()
    cache.store["rank:NSE:2026-01-20"] = [1]
    cache.store["score:NSE:2026-01-20"] = [2]
    monkeypatch.setattr(consumers, "get_cache", lambda: cache)
    bus = InProcessEventBus()
    register_pipeline_consumers(bus)
    bus.publish(
        "ScoresComputed",
        {"universe": "NSE", "date": "2026-01-20", "model_version": "score-v1", "count": 5},
    )
    assert set(cache.deleted) == {"rank:NSE:2026-01-20", "score:NSE:2026-01-20"}
    assert cache.get("rank:NSE:2026-01-20") is None

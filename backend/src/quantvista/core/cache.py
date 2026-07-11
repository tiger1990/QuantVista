"""Cache seam (QV-031) — Redis cache-aside for scores/rankings, TTL-backstopped.

`ICache` is the seam; `RedisCache` is the prod impl (lazy connect, JSON values, per-key TTL) and
`NullCache` a no-op for dev/tests with no Redis. Reads populate the cache; the `ScoresComputed`
event invalidates it (see `jobs/consumers.on_scores_computed`); the TTL bounds staleness if an event
is ever missed (`03` §8). ``core`` foundation — imports no bounded context; Redis import is lazy.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from quantvista.core.config import get_settings


@runtime_checkable
class ICache(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    def delete(self, *keys: str) -> None: ...

    def delete_pattern(self, pattern: str) -> None: ...


class NullCache:
    """No-op cache — every read misses. Used when caching is disabled / Redis is absent."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        return None

    def delete(self, *keys: str) -> None:
        return None

    def delete_pattern(self, pattern: str) -> None:
        return None


class RedisCache:
    """Redis-backed cache — JSON values, per-key TTL. Lazy connect (no redis import at load)."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any | None = None

    def _redis(self) -> Any:
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(self._url, decode_responses=True)
        return self._client

    def get(self, key: str) -> Any | None:
        raw = self._redis().get(key)
        return json.loads(raw) if raw is not None else None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        # ex=None → no expiry; ex=N → N-second TTL (backstop). One call, no deprecated setex.
        self._redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)

    def delete(self, *keys: str) -> None:
        if keys:
            self._redis().delete(*keys)

    def delete_pattern(self, pattern: str) -> None:
        """Delete every key matching a glob ``pattern`` (SCAN, non-blocking)."""
        client = self._redis()
        keys = list(client.scan_iter(match=pattern, count=500))
        if keys:
            client.delete(*keys)


_cache: ICache | None = None


def get_cache() -> ICache:
    """Process-wide cache singleton — ``RedisCache`` when enabled, else ``NullCache``."""
    global _cache
    if _cache is None:
        settings = get_settings()
        _cache = RedisCache(settings.redis_url) if settings.cache_enabled else NullCache()
    return _cache


def reset_cache() -> None:
    """Drop the singleton (tests)."""
    global _cache
    _cache = None

"""RedisStreamEventBus round-trip over a live Redis (QV-024).

Skips if Redis is unreachable (mirrors the DB integration pattern). Uses a unique stream name per
run so nothing collides; the reader thread is stopped + the stream deleted on teardown. Validated
with a SYNTHETIC handler (no real domain consumer until QV-025).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest

from quantvista.core.events import RedisStreamEventBus

pytestmark = pytest.mark.integration

_REDIS_URL = "redis://localhost:6379/0"


def _redis_or_skip() -> Any:
    try:
        import redis

        client = redis.Redis.from_url(_REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        client.ping()
        return client
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Redis not reachable: {exc}")


@pytest.fixture
def topic() -> Iterator[str]:
    client = _redis_or_skip()
    name = f"qv-test-{uuid4().hex[:10]}"
    yield name
    client.delete(name)


def _wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_publish_is_delivered_to_a_subscribed_handler(topic: str) -> None:
    bus = RedisStreamEventBus(_REDIS_URL, group=f"g-{uuid4().hex[:6]}")
    received: list[dict[str, object]] = []
    bus.subscribe(topic, lambda env: received.append(env))
    bus.start()
    try:
        bus.publish(topic, {"market": "NSE", "n": 7})
        assert _wait_for(lambda: len(received) == 1), "handler never received the event"
    finally:
        bus.stop()
    env = received[0]
    assert set(env) == {"event_id", "occurred_at", "topic", "version", "payload"}
    assert env["topic"] == topic and env["payload"] == {"market": "NSE", "n": 7}


def test_handler_error_is_isolated_across_the_stream(topic: str) -> None:
    bus = RedisStreamEventBus(_REDIS_URL, group=f"g-{uuid4().hex[:6]}")
    good: list[dict[str, object]] = []

    def boom(_env: dict[str, object]) -> None:
        raise RuntimeError("consumer down")

    bus.subscribe(topic, boom)
    bus.subscribe(topic, lambda env: good.append(env))
    bus.start()
    try:
        bus.publish(topic, {"x": 1})
        assert _wait_for(lambda: len(good) == 1), "sibling handler never ran"
    finally:
        bus.stop()
    assert good[0]["payload"] == {"x": 1}  # sibling delivered despite the first handler raising

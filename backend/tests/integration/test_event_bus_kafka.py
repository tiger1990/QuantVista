"""KafkaEventBus round-trip over a live broker (QV-024).

Skips unless (a) kafka-python-ng (the [kafka] extra) is importable AND (b) a broker answers on
localhost:9092. Runs locally against ~/kafka (see the kafka-local-feasibility memory); skips in CI
(no Kafka service). Validated with a SYNTHETIC handler (no real domain consumer until QV-025).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from uuid import uuid4

import pytest

from quantvista.core.events import KafkaEventBus

pytestmark = pytest.mark.integration

_BOOTSTRAP = "localhost:9092"


def _broker_or_skip() -> None:
    try:
        import kafka  # noqa: F401
    except ImportError:
        pytest.skip("kafka-python-ng not installed ([kafka] extra)")
    import socket

    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("localhost", 9092))
    except OSError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Kafka broker not reachable: {exc}")
    finally:
        s.close()


@pytest.fixture
def topic() -> Iterator[str]:
    _broker_or_skip()
    yield f"qv-test-{uuid4().hex[:10]}"  # auto-created by the broker on first send


def _wait_for(predicate: Callable[[], bool], timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_publish_is_delivered_to_a_subscribed_handler(topic: str) -> None:
    bus = KafkaEventBus(_BOOTSTRAP, group=f"g-{uuid4().hex[:6]}")
    received: list[dict[str, object]] = []
    bus.subscribe(topic, lambda env: received.append(env))
    bus.start()
    try:
        bus.publish(topic, {"market": "NSE", "n": 9})
        assert _wait_for(lambda: len(received) == 1), "handler never received the event"
    finally:
        bus.stop()
    env = received[0]
    assert set(env) == {"event_id", "occurred_at", "topic", "version", "payload"}
    assert env["topic"] == topic and env["payload"] == {"market": "NSE", "n": 9}

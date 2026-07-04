"""Event bus — one ``IEventBus`` contract, three config-toggled backends (QV-024).

``publish(topic, dict)`` + ``subscribe(topic, handler)`` decouple producers from consumers
(``02`` §7). Every event is wrapped in a stable **envelope** —
``{event_id, occurred_at, topic, version, payload}`` — so replay / idempotency / DLQ / tracing are
reserved, and JSON is the wire format across all transports. ``Settings.event_bus_backend`` selects:

- ``in_process``    — synchronous, in-process dispatch (dev / idle).
- ``redis_streams`` — ``XADD`` + consumer-group reader (at-least-once).
- ``kafka``         — ``KafkaProducer`` + ``KafkaConsumer`` group (lazy ``kafka-python-ng``).

All three share the same handler shape ``Callable[[dict], None]`` receiving the envelope, so
switching backend is a config toggle — zero producer / handler / schema change. ``core`` is the DAG
foundation: this imports no bounded context.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import structlog

from quantvista.core.config import get_settings
from quantvista.core.interfaces import IEventBus

Handler = Callable[[dict[str, Any]], None]


def build_envelope(topic: str, payload: dict[str, Any], version: int = 1) -> dict[str, Any]:
    """Wrap a payload in the reserved event envelope (unique ``event_id``, publish-time stamp)."""
    return {
        "event_id": str(uuid4()),
        "occurred_at": datetime.now(UTC).isoformat(),
        "topic": topic,
        "version": version,
        "payload": payload,
    }


def _dispatch(handlers: list[Handler], envelope: dict[str, Any], log: Any) -> None:
    """Deliver an envelope to each handler, isolated — one failure never blocks the others."""
    for handler in handlers:
        try:
            handler(envelope)
        except Exception:
            log.exception(
                "event_handler_failed", topic=envelope["topic"], event_id=envelope["event_id"]
            )


class LoggingEventBus:
    """Publish-only bus that logs events (legacy default; superseded by the configured backend)."""

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        structlog.get_logger().info("event_published", topic=topic, **event)

    def subscribe(self, topic: str, handler: object) -> None:  # pragma: no cover - not used
        raise NotImplementedError("LoggingEventBus is publish-only; use get_event_bus()")


class InProcessEventBus:
    """Synchronous in-process pub/sub. ``publish`` dispatches inline to each subscribed handler."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._log = structlog.get_logger()

    def subscribe(self, topic: str, handler: object) -> None:
        self._handlers.setdefault(topic, []).append(cast(Handler, handler))

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        envelope = build_envelope(topic, event)
        self._log.info("event_published", topic=topic, event_id=envelope["event_id"])
        _dispatch(self._handlers.get(topic, []), envelope, self._log)

    def start(self) -> None:  # no-op — nothing to run for in-process
        return None

    def stop(self) -> None:
        return None


class RedisStreamEventBus:
    """Redis Streams backend: ``XADD`` to publish; a consumer-group reader thread delivers.

    At-least-once (``XREADGROUP`` → dispatch → ``XACK``). Call ``start()`` to run the reader,
    ``stop()`` to join it. ``redis`` (already a core dep) is imported lazily.
    """

    def __init__(self, redis_url: str, group: str, consumer: str = "c1") -> None:
        self._url = redis_url
        self._group = group
        self._consumer = consumer
        self._handlers: dict[str, list[Handler]] = {}
        self._client: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._log = structlog.get_logger()

    def _redis(self) -> Any:
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(self._url, decode_responses=True)
        return self._client

    def subscribe(self, topic: str, handler: object) -> None:
        self._handlers.setdefault(topic, []).append(cast(Handler, handler))

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        envelope = build_envelope(topic, event)
        self._redis().xadd(topic, {"data": json.dumps(envelope)})
        self._log.info("event_published", topic=topic, event_id=envelope["event_id"])

    def start(self) -> None:
        import redis

        client = self._redis()
        for topic in self._handlers:
            try:  # create the group at the stream end ("$" = only new messages), MKSTREAM
                client.xgroup_create(topic, self._group, id="$", mkstream=True)
            except redis.ResponseError as exc:  # group already exists → fine
                if "BUSYGROUP" not in str(exc):
                    raise
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        client = self._redis()
        streams = {t: ">" for t in self._handlers}
        while not self._stop.is_set():
            try:
                resp = client.xreadgroup(self._group, self._consumer, streams, count=10, block=200)
                for topic, entries in resp or []:
                    for msg_id, fields in entries:
                        envelope = json.loads(fields["data"])
                        _dispatch(self._handlers.get(topic, []), envelope, self._log)
                        client.xack(topic, self._group, msg_id)
            except Exception:  # keep the reader alive on transient errors
                self._log.exception("redis_stream_reader_error")
                self._stop.wait(0.5)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None


class KafkaEventBus:
    """Kafka backend: ``KafkaProducer`` to publish; a ``KafkaConsumer`` group reader delivers.

    ``kafka-python-ng`` (pure-Python, the ``[kafka]`` extra) is imported lazily — importing this
    module never requires it or a running broker.
    """

    def __init__(self, bootstrap_servers: str, group: str) -> None:
        self._bootstrap = bootstrap_servers
        self._group = group
        self._handlers: dict[str, list[Handler]] = {}
        self._producer: Any = None
        self._consumer: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._log = structlog.get_logger()

    def _kafka(self) -> Any:
        try:
            import kafka
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise RuntimeError(
                "kafka event bus needs the [kafka] extra: pip install -e '.[kafka]'"
            ) from exc
        return kafka

    def subscribe(self, topic: str, handler: object) -> None:
        self._handlers.setdefault(topic, []).append(cast(Handler, handler))

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        envelope = build_envelope(topic, event)
        if self._producer is None:
            self._producer = self._kafka().KafkaProducer(
                bootstrap_servers=self._bootstrap,
                value_serializer=lambda v: json.dumps(v).encode(),
            )
        self._producer.send(topic, envelope)
        self._producer.flush()
        self._log.info("event_published", topic=topic, event_id=envelope["event_id"])

    def start(self) -> None:
        self._consumer = self._kafka().KafkaConsumer(
            *self._handlers,
            bootstrap_servers=self._bootstrap,
            group_id=self._group,
            value_deserializer=lambda b: json.loads(b.decode()),
            auto_offset_reset="earliest",
            consumer_timeout_ms=500,
        )
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                for msg in self._consumer:  # consumer_timeout_ms breaks the loop when idle
                    _dispatch(self._handlers.get(msg.topic, []), msg.value, self._log)
                    if self._stop.is_set():
                        break
            except Exception:
                self._log.exception("kafka_reader_error")
                self._stop.wait(0.2)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self._consumer is not None:
            self._consumer.close()
        if self._producer is not None:
            self._producer.close()


# --- factory + process singleton ---------------------------------------------
_bus: IEventBus | None = None


def _make_bus(backend: str) -> IEventBus:
    settings = get_settings()
    if backend == "in_process":
        return InProcessEventBus()
    if backend == "redis_streams":
        return RedisStreamEventBus(settings.redis_url, settings.event_bus_group)
    if backend == "kafka":
        return KafkaEventBus(settings.kafka_bootstrap_servers, settings.event_bus_group)
    raise ValueError(f"unknown event_bus_backend: {backend!r}")


def get_event_bus() -> IEventBus:
    """The process-shared event bus for the configured backend (``Settings.event_bus_backend``)."""
    global _bus
    if _bus is None:
        _bus = _make_bus(get_settings().event_bus_backend)
    return _bus


def reset_event_bus() -> None:
    """Drop the shared bus (stopping any reader thread) — for tests / reconfiguration."""
    global _bus
    if _bus is not None:
        stop = getattr(_bus, "stop", None)
        if callable(stop):
            with contextlib.suppress(Exception):  # best-effort teardown
                stop()
    _bus = None

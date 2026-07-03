"""Default event-bus implementations (QV-016).

``LoggingEventBus`` satisfies ``core.interfaces.IEventBus`` by emitting each published event as
a structured log line. It is the safe default until the real **Redis Streams** bus lands
(QV-024). ``core`` is the foundation layer — this imports no bounded context.
"""

from __future__ import annotations

from typing import Any

import structlog


class LoggingEventBus:
    """Publish-only event bus that logs events (placeholder for Redis Streams, QV-024)."""

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        structlog.get_logger().info("event_published", topic=topic, **event)

    def subscribe(self, topic: str, handler: object) -> None:  # pragma: no cover - QV-024
        raise NotImplementedError("subscription requires the Redis Streams bus (QV-024)")

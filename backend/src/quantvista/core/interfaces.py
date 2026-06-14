"""Platform/Core published interfaces.

Cross-cutting seams used by every context. Core is the foundation of the dependency
DAG: it is imported by all contexts and imports no domain context.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IEventBus(Protocol):
    """Publish/subscribe seam for domain events (Redis Streams in production)."""

    def publish(self, topic: str, event: dict[str, Any]) -> None: ...

    def subscribe(self, topic: str, handler: object) -> None: ...


@runtime_checkable
class IAuditLogger(Protocol):
    """Append-only audit trail for security/compliance-relevant actions."""

    def record(
        self,
        action: str,
        *,
        actor_id: str | None = None,
        tenant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

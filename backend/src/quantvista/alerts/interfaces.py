"""Notifications & Alerts published interfaces.

Tenant-scoped domain (RLS-enforced). Top of the domain DAG: depends on Analytics +
Portfolio (through interfaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class IAlertService(Protocol):
    """Alert-rule evaluation with deduplication."""

    def evaluate(self, tenant_id: UUID) -> int: ...


@dataclass(frozen=True, slots=True)
class DeliveryTarget:
    """Everything a channel needs to deliver one fired alert (QV-049)."""

    tenant_id: UUID
    user_id: UUID
    email: str
    payload: dict[str, Any]


@runtime_checkable
class INotificationChannel(Protocol):
    """A delivery channel (in-app, email, …). The session/sender it needs is injected at
    construction; ``deliver`` raises on failure (the caller records status per event)."""

    def deliver(self, target: DeliveryTarget) -> None: ...

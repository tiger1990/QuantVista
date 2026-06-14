"""Notifications & Alerts published interfaces.

Tenant-scoped domain (RLS-enforced). Top of the domain DAG: depends on Analytics +
Portfolio (through interfaces).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class IAlertService(Protocol):
    """Alert-rule evaluation with deduplication."""

    def evaluate(self, tenant_id: UUID) -> int: ...


@runtime_checkable
class INotificationChannel(Protocol):
    """A delivery channel (in-app, email, …)."""

    def send(self, recipient: str, payload: dict[str, Any]) -> None: ...

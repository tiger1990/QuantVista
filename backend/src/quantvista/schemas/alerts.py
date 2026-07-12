"""Alert wire DTOs (QV-047) — ``04`` §3.7 ``POST /alerts {scope, target_id, condition, channel}``.

Pydantic pins the closed sets (scope/channel/op) at the edge; the domain ``alerts.rules`` allow-list
is the authoritative re-check (metric + numeric value) before anything is stored.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AlertConditionSchema(BaseModel):
    metric: str = Field(min_length=1, max_length=40)
    op: Literal["gte", "lte", "gt", "lt", "eq"]
    value: float


class CreateAlertRequest(BaseModel):
    scope: Literal["stock", "portfolio"]
    target_id: UUID
    condition: AlertConditionSchema
    channel: Literal["email", "in_app"]


class AlertRule(BaseModel):
    id: str
    scope: str
    target_id: str
    condition: dict[str, Any]
    channel: str
    is_active: bool
    created_at: str

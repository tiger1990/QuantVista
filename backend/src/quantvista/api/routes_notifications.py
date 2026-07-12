"""Notification-center endpoints (QV-050) — GET /notifications + POST /notifications/read.

Tenant-isolated via the RLS session, and further scoped to the current user (a tenant may have
several members). The list feeds the in-app bell; ``read`` marks the user's unread as read.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from quantvista.alerts.repositories import list_notifications, mark_all_notifications_read
from quantvista.api.deps import get_tenant_context, get_tenant_session
from quantvista.identity.models import TenantContext
from quantvista.schemas.envelope import Envelope
from quantvista.schemas.notifications import Notification

router = APIRouter(prefix="/api/v1", tags=["notifications"])

_MAX_LIMIT = 100


@router.get("/notifications", response_model=Envelope[list[Notification]])
def list_notifications_endpoint(
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[list[dict[str, Any]]]:
    """The current user's recent notifications (newest first)."""
    rows = list_notifications(session, ctx.user_id, limit)
    return Envelope.ok([Notification.model_validate(r).model_dump() for r in rows])


@router.post("/notifications/read", response_model=Envelope[dict[str, int]])
def mark_read_endpoint(
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[dict[str, int]]:
    """Mark all of the current user's unread notifications read; returns the count updated."""
    updated = mark_all_notifications_read(session, ctx.user_id)
    return Envelope.ok({"marked_read": updated})


__all__ = ["router"]

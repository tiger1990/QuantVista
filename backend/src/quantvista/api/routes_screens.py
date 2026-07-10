"""Saved-screen endpoints (QV-039) — POST/GET/DELETE /screens (04 §3.4).

Tenant-isolated via the RLS session; the ``saved_screens`` tier limit is enforced on create
(US-06). Criteria are validated with the QV-038 allow-list before persisting — a saved screen is
always runnable via ``/screener``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quantvista.analytics.saved_screens import (
    count_saved_screens,
    create_saved_screen,
    delete_saved_screen,
    list_saved_screens,
)
from quantvista.analytics.screener import build_order, build_where
from quantvista.api.deps import get_entitlement_service, get_tenant_context, get_tenant_session
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import EntitlementExceeded, TenantContext
from quantvista.schemas.envelope import Envelope
from quantvista.schemas.screens import SavedScreen, SaveScreenRequest

router = APIRouter(prefix="/api/v1", tags=["screens"])

_LIMIT_KEY = "saved_screens"


class ScreenNameTaken(Exception):
    def __init__(self, name: str) -> None:
        self.name = name


class ScreenNotFound(Exception):
    def __init__(self, screen_id: UUID) -> None:
        self.screen_id = screen_id


@router.post("/screens", response_model=Envelope[SavedScreen], status_code=201)
def create_screen_endpoint(
    body: SaveScreenRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
    entitlements: EntitlementService = Depends(get_entitlement_service),
) -> Envelope[dict[str, Any]]:
    """Save a screen, tier-limited by the ``saved_screens`` entitlement."""
    build_where(body.criteria.filters)  # ScreenerError → 422 (never store an unrunnable screen)
    build_order(body.criteria.sort)

    limit = entitlements.limit(ctx.tenant_id, _LIMIT_KEY)  # None = unlimited
    if limit is not None and count_saved_screens(session) >= limit:
        raise EntitlementExceeded(_LIMIT_KEY)

    try:
        row = create_saved_screen(
            session,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            name=body.name,
            criteria=body.criteria.model_dump(),
        )
    except IntegrityError as exc:
        raise ScreenNameTaken(body.name) from exc
    return Envelope.ok(SavedScreen.model_validate(row).model_dump())


@router.get("/screens", response_model=Envelope[list[SavedScreen]])
def list_screens_endpoint(
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[list[dict[str, Any]]]:
    items = [SavedScreen.model_validate(r).model_dump() for r in list_saved_screens(session)]
    return Envelope.ok(items)


@router.delete("/screens/{screen_id}", status_code=204)
def delete_screen_endpoint(
    screen_id: UUID,
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Response:
    if not delete_saved_screen(session, screen_id):
        raise ScreenNotFound(screen_id)
    return Response(status_code=204)


__all__ = ["ScreenNameTaken", "ScreenNotFound", "router"]

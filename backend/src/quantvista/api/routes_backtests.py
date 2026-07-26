"""Backtest endpoints (QV-062) — async submit + poll (04 §3.6).

Tenant-isolated via the RLS session. ``POST /backtests`` validates the spec (allow-list), gates on
the ``backtest`` entitlement (+ ``backtest_full`` for a >1-year range), persists a queued row,
enqueues the runner, and returns **202**. ``GET /backtests/{id}`` polls; ``GET /backtests`` lists.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from quantvista.analytics.backtests import create_backtest, get_backtest, list_backtests
from quantvista.api.deps import get_entitlement_service, get_tenant_context, get_tenant_session
from quantvista.core.tasks import enqueue
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import TenantContext
from quantvista.schemas.backtest import (
    BacktestListItem,
    BacktestResponse,
    SubmitBacktestRequest,
)
from quantvista.schemas.envelope import Envelope

router = APIRouter(prefix="/api/v1", tags=["backtests"])

_SUBMIT_KEY = "backtest"
_FULL_KEY = "backtest_full"
_PRESET_MAX_DAYS = 366  # ≤ 1 year is a Pro preset; longer needs backtest_full (Quant)


class BacktestNotFound(Exception):
    def __init__(self, backtest_id: UUID) -> None:
        self.backtest_id = backtest_id


def _list_item(row: dict[str, Any]) -> dict[str, Any]:
    spec = row["spec"]
    return BacktestListItem(
        id=str(row["id"]),
        status=str(row["status"]),
        type=str(spec.get("type", "")),
        universe=str(spec.get("universe", "")),
        start=str(spec.get("start", "")),
        end=str(spec.get("end", "")),
        created_at=str(row["created_at"]),
    ).model_dump()


@router.post("/backtests", response_model=Envelope[dict[str, str]], status_code=202)
def submit_backtest_endpoint(
    body: SubmitBacktestRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
    entitlements: EntitlementService = Depends(get_entitlement_service),
) -> Envelope[dict[str, str]]:
    """Queue a backtest → 202 ``{id, status:"queued"}``. Entitlement is checked AFTER validation."""
    spec = body.spec  # already validated (422 on a bad spec)
    entitlements.check(ctx.tenant_id, _SUBMIT_KEY)  # Free (no flag) → 403
    if (spec.end - spec.start).days > _PRESET_MAX_DAYS:
        entitlements.check(ctx.tenant_id, _FULL_KEY)  # custom/long range → Pro-limited → 403

    row = create_backtest(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        spec=spec.model_dump(mode="json"),
    )
    # Enqueue AFTER the row is persisted (the worker reads it by id on a privileged session). By
    # NAME via the core producer seam — `api` may not import `jobs` (sibling composition roots).
    enqueue("quantvista.run_backtest", row["id"])
    return Envelope.ok({"id": str(row["id"]), "status": "queued"})


@router.get("/backtests", response_model=Envelope[list[BacktestListItem]])
def list_backtests_endpoint(
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[list[dict[str, Any]]]:
    return Envelope.ok([_list_item(r) for r in list_backtests(session)])


@router.get("/backtests/{backtest_id}", response_model=Envelope[BacktestResponse])
def get_backtest_endpoint(
    backtest_id: UUID,
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[dict[str, Any]]:
    row = get_backtest(session, backtest_id)  # RLS-scoped: foreign/unknown → None
    if row is None:
        raise BacktestNotFound(backtest_id)
    return Envelope.ok(BacktestResponse.model_validate(row).model_dump())


__all__ = ["BacktestNotFound", "router"]

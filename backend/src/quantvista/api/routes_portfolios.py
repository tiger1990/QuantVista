"""Portfolio & position endpoints (QV-052) — CRUD under /portfolios (04 §3.5).

Tenant-isolated via the RLS session (a portfolio that isn't the tenant's is invisible → 404, never
a 403 that leaks existence). ``POST /portfolios`` enforces the ``portfolios`` entitlement (US-06)
and honors ``Idempotency-Key``; positions use ``PUT`` (upsert is naturally idempotent) and validate
that target weights don't over-allocate the portfolio. Money/weights are ``Decimal`` on the wire.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from quantvista.api.deps import get_entitlement_service, get_tenant_context, get_tenant_session
from quantvista.api.idempotency import idempotent
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import TenantContext
from quantvista.portfolio.repositories import (
    count_portfolios,
    create_portfolio,
    delete_portfolio,
    delete_position,
    get_portfolio,
    list_portfolios,
    list_positions,
    upsert_position,
)
from quantvista.portfolio.services import (
    PORTFOLIO_LIMIT_KEY,
    enforce_portfolio_limit,
    validate_position_weights,
)
from quantvista.schemas.envelope import Envelope
from quantvista.schemas.portfolios import (
    CreatePortfolioRequest,
    Portfolio,
    Position,
    UpsertPositionRequest,
)

router = APIRouter(prefix="/api/v1", tags=["portfolios"])

_CREATE_PATH = "/api/v1/portfolios"


class PortfolioNotFound(Exception):
    def __init__(self, portfolio_id: UUID) -> None:
        self.portfolio_id = portfolio_id


class PositionNotFound(Exception):
    def __init__(self, portfolio_id: UUID, stock_id: UUID) -> None:
        self.portfolio_id = portfolio_id
        self.stock_id = stock_id


@router.post("/portfolios", response_model=Envelope[Portfolio], status_code=201)
def create_portfolio_endpoint(
    body: CreatePortfolioRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
    entitlements: EntitlementService = Depends(get_entitlement_service),
) -> Response:
    """Create a portfolio (``portfolios`` entitlement enforced; ``Idempotency-Key`` de-duplicated).

    The limit check lives inside ``_produce`` so a replay returns the original 201 — the created
    portfolio already counts against the quota and must not re-trip the guard.
    """

    def _produce() -> tuple[int, dict[str, Any]]:
        limit = entitlements.limit(ctx.tenant_id, PORTFOLIO_LIMIT_KEY)  # None = unlimited
        enforce_portfolio_limit(current_count=count_portfolios(session), limit=limit)
        row = create_portfolio(
            session,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            name=body.name,
            benchmark=body.benchmark,
            base_currency=body.base_currency,
        )
        envelope = Envelope.ok(Portfolio.model_validate(row).model_dump())
        return 201, jsonable_encoder(envelope)

    if idempotency_key:
        status, payload = idempotent(
            session,
            tenant_id=ctx.tenant_id,
            key=idempotency_key,
            method="POST",
            path=_CREATE_PATH,
            body=body.model_dump(mode="json"),
            produce=_produce,
        )
    else:
        status, payload = _produce()
    return JSONResponse(status_code=status, content=payload)


@router.get("/portfolios", response_model=Envelope[list[Portfolio]])
def list_portfolios_endpoint(
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[list[dict[str, Any]]]:
    items = [Portfolio.model_validate(r).model_dump() for r in list_portfolios(session)]
    return Envelope.ok(items)


@router.get("/portfolios/{portfolio_id}", response_model=Envelope[Portfolio])
def get_portfolio_endpoint(
    portfolio_id: UUID,
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[dict[str, Any]]:
    row = get_portfolio(session, portfolio_id)
    if row is None:
        raise PortfolioNotFound(portfolio_id)
    return Envelope.ok(Portfolio.model_validate(row).model_dump())


@router.delete("/portfolios/{portfolio_id}", status_code=204)
def delete_portfolio_endpoint(
    portfolio_id: UUID,
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Response:
    if not delete_portfolio(session, portfolio_id):
        raise PortfolioNotFound(portfolio_id)
    return Response(status_code=204)


@router.put("/portfolios/{portfolio_id}/positions/{stock_id}", response_model=Envelope[Position])
def upsert_position_endpoint(
    portfolio_id: UUID,
    stock_id: UUID,
    body: UpsertPositionRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[dict[str, Any]]:
    """Upsert a position, rejecting a set of target weights that over-allocates the portfolio."""
    if get_portfolio(session, portfolio_id) is None:  # parent not the tenant's / absent → 404
        raise PortfolioNotFound(portfolio_id)

    # Project the post-upsert target weights (existing minus this stock, plus the incoming) and
    # validate the total ≤ 1 before writing.
    projected: list[Decimal | None] = [
        cast("Decimal | None", p["target_weight"])
        for p in list_positions(session, portfolio_id)
        if UUID(str(p["stock_id"])) != stock_id
    ]
    if body.target_weight is not None:
        projected.append(body.target_weight)
    validate_position_weights(projected)

    row = upsert_position(
        session,
        tenant_id=ctx.tenant_id,
        portfolio_id=portfolio_id,
        stock_id=stock_id,
        weight=body.weight,
        target_weight=body.target_weight,
        shares=body.shares,
        avg_cost=body.avg_cost,
    )
    return Envelope.ok(Position.model_validate(row).model_dump())


@router.get("/portfolios/{portfolio_id}/positions", response_model=Envelope[list[Position]])
def list_positions_endpoint(
    portfolio_id: UUID,
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[list[dict[str, Any]]]:
    if get_portfolio(session, portfolio_id) is None:
        raise PortfolioNotFound(portfolio_id)
    items = [Position.model_validate(r).model_dump() for r in list_positions(session, portfolio_id)]
    return Envelope.ok(items)


@router.delete("/portfolios/{portfolio_id}/positions/{stock_id}", status_code=204)
def delete_position_endpoint(
    portfolio_id: UUID,
    stock_id: UUID,
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Response:
    if not delete_position(session, portfolio_id, stock_id):
        raise PositionNotFound(portfolio_id, stock_id)
    return Response(status_code=204)


__all__ = ["PortfolioNotFound", "PositionNotFound", "router"]

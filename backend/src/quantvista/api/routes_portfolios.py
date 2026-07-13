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
from quantvista.api.routes_stocks import DISCLAIMER, _with_disclaimer
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import TenantContext
from quantvista.market_data.repositories import latest_price_date, sectors_for
from quantvista.market_data.returns import returns_matrix_as_of
from quantvista.portfolio.constraints import Constraints
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
from quantvista.schemas.optimize import (
    ConstraintStatusDTO,
    OptimizeConstraints,
    OptimizeRequest,
    OptimizeResponse,
)
from quantvista.schemas.portfolios import (
    CreatePortfolioRequest,
    Portfolio,
    Position,
    UpsertPositionRequest,
)

router = APIRouter(prefix="/api/v1", tags=["portfolios"])

_CREATE_PATH = "/api/v1/portfolios"

# Optimize (QV-055): endpoint requires the `optimization` flag; BL/HRP additionally need
# `optimization_advanced`. Only mean_variance is implemented (risk_parity → QV-057). The returns
# matrix is built over ~2y of PIT history.
_OPTIMIZE_KEY = "optimization"
_ADVANCED_KEY = "optimization_advanced"
_ADVANCED_METHODS = frozenset({"black_litterman", "hrp"})
_LOOKBACK_DAYS = 730
_MIN_OBSERVATIONS = 60


class PortfolioNotFound(Exception):
    def __init__(self, portfolio_id: UUID) -> None:
        self.portfolio_id = portfolio_id


class PositionNotFound(Exception):
    def __init__(self, portfolio_id: UUID, stock_id: UUID) -> None:
        self.portfolio_id = portfolio_id
        self.stock_id = stock_id


class OptimizeError(Exception):
    """A bad optimize request (unavailable method, no positions/prices) → validation_error."""


def _to_constraints(dto: OptimizeConstraints) -> Constraints:
    """Map the wire DTO to the frozen QV-053 ``Constraints`` (api layer — schemas can't import)."""
    return Constraints(
        max_weight=dto.max_weight,
        min_weight=dto.min_weight if dto.min_weight is not None else Decimal(0),
        long_only=dto.long_only,
        sector_caps=dict(dto.sector_caps),
        cardinality_min=dto.cardinality_min,
        cardinality_max=dto.cardinality_max,
        target_volatility=dto.target_volatility,
        target_return=dto.target_return,
        max_turnover=dto.max_turnover,
    )


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


@router.post("/portfolios/{portfolio_id}/optimize", response_model=Envelope[OptimizeResponse])
def optimize_portfolio_endpoint(
    portfolio_id: UUID,
    body: OptimizeRequest,
    response: Response,
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
    entitlements: EntitlementService = Depends(get_entitlement_service),
) -> Envelope[dict[str, Any]]:
    """Optimize a portfolio's allocation (research signal, not advice — US-03/D1).

    Entitlement-gated (``optimization``; BL/HRP also ``optimization_advanced``), tenant-scoped
    (unknown/foreign portfolio → 404). Builds a PIT returns matrix from the current positions and
    runs the QV-054 mean-variance optimizer; an infeasible problem surfaces as ``infeasible`` (422)
    with the binding constraint. cvxpy is imported lazily so ``create_app()`` stays importable
    without the ``portfolio`` extra.
    """
    entitlements.check(ctx.tenant_id, _OPTIMIZE_KEY)
    if body.method in _ADVANCED_METHODS:
        entitlements.check(ctx.tenant_id, _ADVANCED_KEY)
    if get_portfolio(session, portfolio_id) is None:  # RLS-invisible / absent → 404
        raise PortfolioNotFound(portfolio_id)
    if body.method != "mean_variance":  # risk_parity → QV-057; BL/HRP → later
        raise OptimizeError(f"method '{body.method}' is not yet available")

    stock_ids = [UUID(str(p["stock_id"])) for p in list_positions(session, portfolio_id)]
    if not stock_ids:
        raise OptimizeError("portfolio has no positions to optimize")
    as_of = latest_price_date(session)
    if as_of is None:
        raise OptimizeError("no price data available to optimize")

    returns = returns_matrix_as_of(
        session, stock_ids, as_of, lookback_days=_LOOKBACK_DAYS, min_observations=_MIN_OBSERVATIONS
    )
    sector_of = sectors_for(session, stock_ids)

    # Lazy import: pulls cvxpy (the optional `portfolio` extra) only when optimize is actually hit.
    from quantvista.portfolio.optimizer import (
        MeanVarianceOptimizer,
        Objective,
        OptimizationRequest,
    )

    result = MeanVarianceOptimizer().optimize(
        OptimizationRequest(
            objective=Objective(body.objective),
            constraints=_to_constraints(body.constraints),
            risk_free_rate=body.risk_free_rate,
            sector_of=sector_of,
        ),
        returns,
    )
    payload = OptimizeResponse(
        weights={str(sid): str(w) for sid, w in result.weights.items()},
        expected_return=str(result.expected_return),
        expected_volatility=str(result.expected_volatility),
        constraints=[
            ConstraintStatusDTO(kind=s.kind.value, satisfied=s.satisfied, detail=s.detail)
            for s in result.constraint_report.statuses
        ],
    ).model_dump()
    _with_disclaimer(response)
    return Envelope.ok(payload, meta={"disclaimer": DISCLAIMER})


__all__ = ["OptimizeError", "PortfolioNotFound", "PositionNotFound", "router"]

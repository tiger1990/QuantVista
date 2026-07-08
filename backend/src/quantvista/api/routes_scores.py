"""Score endpoints (QV-033) — GET /scores/{symbol}, /decomposition, /rankings.

Authenticated global reads. ``/scores`` + ``/decomposition`` are single-stock (auth only);
``/rankings`` is a composite-desc leaderboard capped by the tenant's ``universe_scores_top``
entitlement (Free → top-50). Decomposition contributions **sum to** the composite (US-02).
Scores are research signals → the disclaimer header + ``meta.disclaimer`` ride every response.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from quantvista.analytics.repositories import latest_score_date, score_of
from quantvista.analytics.services import cached_rankings, decompose
from quantvista.api.deps import (
    get_current_principal,
    get_entitlement_service,
    get_global_session,
    get_tenant_context,
)
from quantvista.api.routes_stocks import DISCLAIMER, StockNotFound, _with_disclaimer
from quantvista.core.cache import get_cache
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import Principal, TenantContext
from quantvista.schemas.envelope import Envelope
from quantvista.schemas.scores import DecompositionResponse, RankingItem, ScoreResponse

router = APIRouter(prefix="/api/v1", tags=["scores"])

_RANKINGS_QUOTA = "universe_scores_top"


def effective_limit(requested: int, tier: int | None) -> int:
    """The served count: the request, capped by the tenant's tier quota (``None`` = unlimited)."""
    return min(requested, tier) if tier is not None else requested


@router.get("/scores/{symbol}", response_model=Envelope[ScoreResponse])
def get_score_endpoint(
    symbol: str,
    response: Response,
    as_of: date | None = Query(None),
    _principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_global_session),
) -> Envelope[dict[str, Any]]:
    """A stock's composite + sub-scores as of ``as_of`` (default latest)."""
    score = score_of(session, symbol, as_of)
    if score is None:
        raise StockNotFound(symbol)
    payload = ScoreResponse.model_validate(
        {
            "symbol": symbol,
            "as_of": cast(date, score["date"]).isoformat(),
            "fundamental": score["fundamental"],
            "momentum": score["momentum"],
            "quality": score["quality"],
            "sentiment": score["sentiment"],
            "risk": score["risk"],
            "composite": score["composite"],
            "coverage": score["coverage"],
            "weights_version": score["weights_version"],
            "model_version": score["model_version"],
        }
    ).model_dump()
    _with_disclaimer(response)
    return Envelope.ok(payload, meta={"disclaimer": DISCLAIMER})


@router.get("/scores/{symbol}/decomposition", response_model=Envelope[DecompositionResponse])
def get_decomposition_endpoint(
    symbol: str,
    response: Response,
    as_of: date | None = Query(None),
    _principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_global_session),
) -> Envelope[dict[str, Any]]:
    """Per-factor contributions that sum to the composite (US-02)."""
    result = decompose(session, symbol, as_of)
    if result is None:
        raise StockNotFound(symbol)
    payload = DecompositionResponse.model_validate(result).model_dump()
    _with_disclaimer(response)
    return Envelope.ok(payload, meta={"disclaimer": DISCLAIMER})


@router.get("/rankings", response_model=Envelope[list[RankingItem]])
def get_rankings_endpoint(
    response: Response,
    universe: str = Query("NIFTY200"),  # informational; dev universe = the market's constituents
    market: str = Query("NSE"),
    as_of: date | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(get_current_principal),
    ctx: TenantContext = Depends(get_tenant_context),
    entitlements: EntitlementService = Depends(get_entitlement_service),
    session: Session = Depends(get_global_session),
) -> Envelope[list[dict[str, Any]]]:
    """Composite-desc leaderboard, truncated to the tenant's ``universe_scores_top`` quota."""
    as_of_date = latest_score_date(session, market=market, on_or_before=as_of)
    _with_disclaimer(response)
    if as_of_date is None:  # nothing scored yet
        return Envelope.ok([], meta={"as_of": None, "tier_limit": None, "truncated": False})

    full = cached_rankings(get_cache(), session, market, as_of_date)
    tier = entitlements.limit(ctx.tenant_id, _RANKINGS_QUOTA)  # None = unlimited
    effective = effective_limit(limit, tier)
    items = [
        RankingItem.model_validate(
            {
                "rank": i + 1,
                "symbol": r["symbol"],
                "composite_score": r["composite_score"],
                "coverage": r["coverage"],
            }
        ).model_dump()
        for i, r in enumerate(full[:effective])
    ]
    return Envelope.ok(
        items,
        meta={
            "as_of": as_of_date.isoformat(),
            "universe": universe,
            "tier_limit": tier,
            "truncated": len(full) > effective,
            "disclaimer": DISCLAIMER,
        },
    )

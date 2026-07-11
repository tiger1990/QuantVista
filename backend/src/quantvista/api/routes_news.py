"""News read endpoints (QV-043) — per-stock + market-wide feeds.

Authenticated global reads over the ``news`` table (QV-041 ingested, QV-042 tagged). The history
window is entitlement-gated by ``news_history_days`` (Free 7d / Pro 1y / Quant unlimited). Text is
rendered client-side (React-escaped) with links out — nothing to sanitize server-side beyond the
derived fields we store. Every response carries the research disclaimer.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from quantvista.api.deps import (
    get_entitlement_service,
    get_global_session,
    get_tenant_context,
)
from quantvista.api.routes_stocks import DISCLAIMER, _with_disclaimer
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import TenantContext
from quantvista.news.repositories import latest_news, news_for_stock
from quantvista.schemas.envelope import Envelope
from quantvista.schemas.news import NewsItem

router = APIRouter(prefix="/api/v1", tags=["news"])

_NEWS_WINDOW_KEY = "news_history_days"
_MAX_LIMIT = 50


def _window_since(entitlements: EntitlementService, tenant_id: Any) -> date | None:
    """Lower bound on ``published_at`` from the plan's ``news_history_days`` (None = unlimited)."""
    days = entitlements.limit(tenant_id, _NEWS_WINDOW_KEY)
    return None if days is None else date.today() - timedelta(days=days)


@router.get("/stocks/{symbol}/news", response_model=Envelope[list[NewsItem]])
def stock_news_endpoint(
    symbol: str,
    response: Response,
    limit: int = Query(20, ge=1, le=_MAX_LIMIT),
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_global_session),
    entitlements: EntitlementService = Depends(get_entitlement_service),
) -> Envelope[list[dict[str, Any]]]:
    """Recent news tagged to ``symbol``, newest-first, within the plan's history window."""
    since = _window_since(entitlements, ctx.tenant_id)
    rows = news_for_stock(session, symbol, since=since, limit=limit)
    items = [NewsItem.model_validate(r).model_dump() for r in rows]
    _with_disclaimer(response)
    return Envelope.ok(items, meta={"disclaimer": DISCLAIMER})


@router.get("/news", response_model=Envelope[list[NewsItem]])
def market_news_endpoint(
    response: Response,
    limit: int = Query(30, ge=1, le=_MAX_LIMIT),
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_global_session),
    entitlements: EntitlementService = Depends(get_entitlement_service),
) -> Envelope[list[dict[str, Any]]]:
    """Market-wide latest news (India-source-first), within the plan's history window."""
    since = _window_since(entitlements, ctx.tenant_id)
    rows = latest_news(session, since=since, limit=limit)
    items = [NewsItem.model_validate(r).model_dump() for r in rows]
    _with_disclaimer(response)
    return Envelope.ok(items, meta={"disclaimer": DISCLAIMER})

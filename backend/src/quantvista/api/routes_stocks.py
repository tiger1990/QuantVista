"""Stock read endpoints (QV-032) — GET /stocks, GET /stocks/{symbol}.

Authenticated, global (no-RLS) reference reads. Cursor-paginated universe browse + a per-symbol
master+snapshot (cached under ``stock:{symbol}:detail``). Scores are research signals → every
response carries the disclaimer header + a ``meta.disclaimer`` field (04 §3.2 / 07). ``Envelope``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from quantvista.analytics.repositories import list_stocks, stock_detail
from quantvista.api.deps import get_current_principal, get_global_session
from quantvista.api.pagination import decode_cursor, encode_cursor
from quantvista.core.cache import get_cache
from quantvista.core.config import get_settings
from quantvista.identity.models import Principal
from quantvista.schemas.envelope import Envelope
from quantvista.schemas.stocks import StockDetail, StockListItem

router = APIRouter(prefix="/api/v1", tags=["stocks"])

DISCLAIMER = "Research signal, not investment advice."
_DISCLAIMER_HEADER = "X-QuantVista-Disclaimer"
_DISCLAIMER_HEADER_VALUE = "research-only; not investment advice"
_MAX_LIMIT = 100


class StockNotFound(Exception):
    """Raised for an unknown symbol → mapped to a 404 `not_found` envelope."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


def _with_disclaimer(response: Response) -> None:
    response.headers[_DISCLAIMER_HEADER] = _DISCLAIMER_HEADER_VALUE


@router.get("/stocks", response_model=None)
def list_stocks_endpoint(
    response: Response,
    market: str = Query("NSE"),
    sector: str | None = Query(None),
    market_cap_bucket: str | None = Query(None),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    _principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_global_session),
) -> Envelope[list[dict[str, Any]]]:
    """Browse the universe: filter by market/sector/cap, keyset-paginated by symbol."""
    after = decode_cursor(cursor)  # raises ValueError → validation_error (422)
    rows = list_stocks(
        session,
        market=market,
        sector=sector,
        market_cap_bucket=market_cap_bucket,
        limit=limit + 1,  # fetch one extra to know if there's a next page
        after_symbol=after,
    )
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(str(rows[-1]["symbol"]))
    items = [StockListItem.model_validate(r).model_dump() for r in rows]
    _with_disclaimer(response)
    return Envelope.ok(items, meta={"next_cursor": next_cursor, "disclaimer": DISCLAIMER})


@router.get("/stocks/{symbol}", response_model=None)
def get_stock_endpoint(
    symbol: str,
    response: Response,
    _principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_global_session),
) -> Envelope[dict[str, Any]]:
    """Master + latest snapshot for ``symbol`` (cached, TTL-backstopped)."""
    cache = get_cache()
    key = f"stock:{symbol}:detail"
    cached = cache.get(key)
    if cached is None:
        detail = stock_detail(session, symbol)
        if detail is None:
            raise StockNotFound(symbol)
        cached = StockDetail.model_validate(detail).model_dump()
        cache.set(key, cached, ttl_seconds=get_settings().cache_ttl_seconds)
    _with_disclaimer(response)
    return Envelope.ok(cached, meta={"disclaimer": DISCLAIMER})

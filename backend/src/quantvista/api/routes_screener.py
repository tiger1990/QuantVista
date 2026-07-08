"""Screener endpoint (QV-038) — POST /screener (04 §3.4).

Validated filter/sort specs against an allow-list (no injection), sort + opaque offset cursor,
``meta.count``. Auth-only (result quotas are QV-039's saved-screens concern). Research data →
the disclaimer rides every response.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from quantvista.analytics.repositories import screen
from quantvista.analytics.screener import ScreenerError, build_order, build_where
from quantvista.api.deps import get_current_principal, get_global_session
from quantvista.api.pagination import InvalidCursor, decode_cursor, encode_cursor
from quantvista.api.routes_stocks import DISCLAIMER, _with_disclaimer
from quantvista.identity.models import Principal
from quantvista.schemas.envelope import Envelope
from quantvista.schemas.screener import ScreenerRow, ScreenRequest

router = APIRouter(prefix="/api/v1", tags=["screener"])


def _offset_from_cursor(cursor: str | None) -> int:
    raw = decode_cursor(cursor)  # None, or a decoded str; raises InvalidCursor on bad base64
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise InvalidCursor() from exc


@router.post("/screener", response_model=Envelope[list[ScreenerRow]])
def screen_endpoint(
    body: ScreenRequest,
    response: Response,
    _principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_global_session),
) -> Envelope[list[dict[str, Any]]]:
    """Filter/sort the universe by any allow-listed factor/fundamental."""
    where_sql, params = build_where(body.filters)  # ScreenerError → 422
    order_sql = build_order(body.sort)
    offset = _offset_from_cursor(body.cursor)

    rows, count = screen(
        session,
        market=body.market,
        where_sql=where_sql,
        params=params,
        order_sql=order_sql,
        limit=body.limit,
        offset=offset,
    )
    items = [ScreenerRow.model_validate(r).model_dump() for r in rows]
    next_cursor = encode_cursor(str(offset + body.limit)) if offset + body.limit < count else None

    _with_disclaimer(response)
    return Envelope.ok(
        items,
        meta={"count": count, "next_cursor": next_cursor, "disclaimer": DISCLAIMER},
    )


__all__ = ["ScreenerError", "router"]

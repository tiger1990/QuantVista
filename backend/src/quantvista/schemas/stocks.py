"""Stock wire DTOs (QV-032). Shared so the generated TS client picks them up.

``StockListItem`` = a `/stocks` list row; ``StockDetail`` = master + ``LatestSnapshot`` for
`/stocks/{symbol}`. Scores are research signals (a ``disclaimer`` rides in the envelope ``meta``).
"""

from __future__ import annotations

from pydantic import BaseModel


class StockListItem(BaseModel):
    symbol: str
    company_name: str
    sector: str | None
    market_cap_bucket: str | None
    market: str
    composite_score: float | None  # latest, nullable when unscored


class LatestSnapshot(BaseModel):
    price_date: str | None
    close: float | None
    composite_score: float | None
    fundamental_score: float | None
    momentum_score: float | None
    quality_score: float | None
    sentiment_score: float | None
    risk_score: float | None
    coverage: float | None
    model_version: str | None
    weights_version: str | None
    pe: float | None
    pb: float | None
    roe: float | None
    roce: float | None
    debt_equity: float | None


class StockDetail(BaseModel):
    symbol: str
    company_name: str
    sector: str | None
    industry: str | None
    market_cap_bucket: str | None
    market: str
    is_active: bool
    snapshot: LatestSnapshot

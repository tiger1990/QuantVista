"""Screener wire DTOs (QV-038). ``04`` §3.4."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FilterClause(BaseModel):
    field: str
    op: str
    value: float | str


class ScreenRequest(BaseModel):
    universe: str = "NIFTY200"  # informational; dev universe = the market's constituents
    market: str = "NSE"
    filters: list[FilterClause] = Field(default_factory=list)
    sort: str | None = None  # e.g. "-composite_score"; default "-composite_score"
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = None


class ScreenerRow(BaseModel):
    symbol: str
    company_name: str
    sector: str | None
    market_cap_bucket: str | None
    market: str
    composite_score: float | None
    fundamental_score: float | None
    momentum_score: float | None
    quality_score: float | None
    sentiment_score: float | None
    risk_score: float | None
    coverage: float | None
    pe: float | None
    pb: float | None
    roe: float | None
    roce: float | None
    debt_equity: float | None

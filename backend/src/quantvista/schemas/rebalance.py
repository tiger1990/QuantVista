"""Rebalance endpoint wire DTOs (QV-059).

``POST /portfolios/{id}/rebalance`` request + response. Pure Pydantic — the
foundation-purity contract forbids ``schemas`` from importing domain contexts, so the
``RebalancePlan`` → DTO mapping lives in the ``api`` layer. Money/ratios serialize as
strings (Decimal-as-string), never ``float``.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RebalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown fields (QV-079)
    drift_threshold: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)


class TradeSuggestionDTO(BaseModel):
    stock_id: str
    symbol: str
    direction: str  # "buy" | "sell"
    current_weight: str  # Decimal-as-string
    target_weight: str  # Decimal-as-string (normalized)
    delta_weight: str  # Decimal-as-string (signed: positive=buy, negative=sell)


class RebalanceResponse(BaseModel):
    as_of_date: str
    total_drift: str  # Decimal-as-string
    needs_rebalance: bool
    trades: list[TradeSuggestionDTO]


__all__ = ["RebalanceRequest", "RebalanceResponse", "TradeSuggestionDTO"]

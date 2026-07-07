"""Score wire DTOs (QV-033). Shared so the generated TS client picks them up.

``ScoreResponse`` = a stock's composite + sub-scores; ``DecompositionResponse`` = per-factor
contributions that **sum to** the composite (US-02); ``RankingItem`` = a leaderboard row.
"""

from __future__ import annotations

from pydantic import BaseModel


class ScoreResponse(BaseModel):
    symbol: str
    as_of: str
    fundamental: float | None
    momentum: float | None
    quality: float | None
    sentiment: float | None
    risk: float | None
    composite: float
    coverage: float | None
    weights_version: str
    model_version: str


class FactorContribution(BaseModel):
    factor_key: str
    category: str
    raw_value: float | None
    zscore: float | None
    percentile_sector: float | None
    percentile_universe: float | None
    contribution: float  # to the composite
    as_of: str  # PIT date the factor was computed for


class DecompositionResponse(BaseModel):
    symbol: str
    as_of: str
    composite: float
    sum_of_contributions: float  # == composite (± rounding)
    factors: list[FactorContribution]


class RankingItem(BaseModel):
    rank: int
    symbol: str
    composite_score: float | None
    coverage: float | None

"""Portfolio & position wire DTOs (QV-052) — ``04`` §3.5.

``POST /portfolios { name, benchmark, base_currency }`` and ``PUT
/portfolios/{id}/positions/{stock_id} { weight?, target_weight?, shares?, avg_cost? }``.
Money/weights are ``Decimal`` (Pydantic v2 serializes them to JSON *strings*, preserving
precision — never ``float``). Per-field ``weight``/``target_weight`` ∈ ``[0, 1]`` is pinned at the
edge here; the cross-position sum-≤-1 rule lives in ``portfolio.services`` (a pure domain guard).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class CreatePortfolioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    benchmark: str = Field(default="NIFTY200_TRI", min_length=1, max_length=40)
    base_currency: str = Field(default="INR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


class Portfolio(BaseModel):
    id: str
    name: str
    benchmark: str
    base_currency: str
    created_at: str
    updated_at: str


class UpsertPositionRequest(BaseModel):
    """``stock_id`` comes from the path, not the body. All fields optional (partial curation)."""

    weight: Decimal | None = Field(default=None, ge=0, le=1)
    target_weight: Decimal | None = Field(default=None, ge=0, le=1)
    shares: Decimal | None = Field(default=None, ge=0)
    avg_cost: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _require_at_least_one(self) -> UpsertPositionRequest:
        if all(v is None for v in (self.weight, self.target_weight, self.shares, self.avg_cost)):
            raise ValueError(
                "at least one of weight, target_weight, shares, or avg_cost must be set"
            )
        return self


class Position(BaseModel):
    id: str
    portfolio_id: str
    stock_id: str
    weight: Decimal | None
    target_weight: Decimal | None
    shares: Decimal | None
    avg_cost: Decimal | None

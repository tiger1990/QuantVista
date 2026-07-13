"""Optimize endpoint wire DTOs (QV-055) — ``04`` §3.5.

``POST /portfolios/{id}/optimize`` request/response. These are **pure** Pydantic DTOs: the
foundation-purity import-linter contract forbids ``schemas`` from importing a domain context, so the
DTO→``Constraints`` mapping and the objective/method gating live in the ``api`` layer, not here.
Per-field ``[0,1]`` bounds and the cross-field checks (mirroring ``portfolio.Constraints``) are
enforced at this edge so a bad request is a Pydantic 422 before it ever reaches the domain.

Money/weights are ``Decimal``; on the wire they serialize as strings (never ``float``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Method = Literal["mean_variance", "risk_parity", "black_litterman", "hrp"]
ObjectiveName = Literal["max_sharpe", "min_vol", "target_return"]


class OptimizeConstraints(BaseModel):
    """Wire form of ``portfolio.Constraints`` (mapped to the domain object in the api layer)."""

    max_weight: Decimal | None = Field(default=None, gt=0, le=1)
    min_weight: Decimal | None = Field(default=None, ge=0, le=1)
    long_only: bool = True
    sector_caps: dict[str, Decimal] = Field(default_factory=dict)
    cardinality_min: int | None = Field(default=None, ge=1)
    cardinality_max: int | None = Field(default=None, ge=1)
    target_volatility: Decimal | None = Field(default=None, gt=0)
    target_return: Decimal | None = None
    max_turnover: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _cross_field(self) -> OptimizeConstraints:
        for sector, cap in self.sector_caps.items():
            if not (Decimal(0) < cap <= Decimal(1)):
                raise ValueError(f"sector cap for {sector!r} must be in (0, 1], got {cap}")
        if (
            self.max_weight is not None
            and self.min_weight is not None
            and self.min_weight > self.max_weight
        ):
            raise ValueError(f"min_weight {self.min_weight} exceeds max_weight {self.max_weight}")
        if (
            self.cardinality_min is not None
            and self.cardinality_max is not None
            and self.cardinality_min > self.cardinality_max
        ):
            raise ValueError("cardinality_min exceeds cardinality_max")
        return self


class OptimizeRequest(BaseModel):
    method: Method
    objective: ObjectiveName
    constraints: OptimizeConstraints = Field(default_factory=OptimizeConstraints)
    candidate_universe: Literal["current_positions"] = "current_positions"
    risk_free_rate: Decimal = Field(default=Decimal(0), ge=0)


class ConstraintStatusDTO(BaseModel):
    kind: str
    satisfied: bool
    detail: str


class OptimizeResponse(BaseModel):
    weights: dict[str, str]  # stock_id → Decimal-as-string
    expected_return: str
    expected_volatility: str
    constraints: list[ConstraintStatusDTO]


__all__ = [
    "ConstraintStatusDTO",
    "Method",
    "ObjectiveName",
    "OptimizeConstraints",
    "OptimizeRequest",
    "OptimizeResponse",
]

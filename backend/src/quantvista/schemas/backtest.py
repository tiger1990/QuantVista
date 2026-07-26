"""Backtest wire DTOs (QV-062). ``04`` §3.6 — async submit + poll.

The ``spec`` is user JSON persisted as JSONB and later executed by the engine (QV-065), so it is
validated with an **allow-list** at the edge (closed ``Literal`` sets, numeric bounds, real dates,
``start < end``) and ``extra="forbid"`` — same discipline as the screener/alert DSLs. The stored
JSONB is the **validated** spec (``model_dump(mode="json")``), re-read canonically by the engine.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RankBy = Literal["composite", "fundamental", "momentum", "quality", "sentiment", "risk"]
Rebalance = Literal["weekly", "monthly", "quarterly"]


class BacktestRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rank_by: RankBy = "composite"
    top_n: int = Field(ge=1, le=200)
    rebalance: Rebalance = "monthly"


class BacktestSpec(BaseModel):
    """A factor-strategy backtest specification (universe, rules, range, costs, benchmark)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["factor_strategy"] = "factor_strategy"
    universe: Literal["NIFTY200"] = "NIFTY200"
    rules: BacktestRules
    start: date
    end: date
    costs_bps: int = Field(default=0, ge=0, le=500)
    benchmark: str = Field(default="NIFTY200_TRI", min_length=1, max_length=40)

    @model_validator(mode="after")
    def _valid_range(self) -> BacktestSpec:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class SubmitBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: BacktestSpec


class BacktestResponse(BaseModel):
    """Poll payload for one backtest."""

    id: str
    status: str
    spec: dict[str, Any]
    metrics: dict[str, Any] | None
    result_ref: str | None
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class BacktestListItem(BaseModel):
    id: str
    status: str
    type: str
    universe: str
    start: str
    end: str
    created_at: str


__all__ = [
    "BacktestListItem",
    "BacktestResponse",
    "BacktestRules",
    "BacktestSpec",
    "SubmitBacktestRequest",
]

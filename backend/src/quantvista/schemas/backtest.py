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


StrategyType = Literal["factor_strategy", "custom_basket"]

MAX_BASKET_SYMBOLS = 50


class BacktestRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rank_by: RankBy = "composite"
    # Defaulted so a ``custom_basket`` — which ranks nothing — need only supply ``rebalance``.
    top_n: int = Field(default=20, ge=1, le=200)
    rebalance: Rebalance = "monthly"


class BacktestSpec(BaseModel):
    """A backtest specification (universe, rules, range, costs, benchmark).

    Two strategy types share one shape: ``factor_strategy`` ranks the universe by a score and holds
    the top N, while ``custom_basket`` equal-weights an explicit, user-chosen ``symbols`` list
    (``rank_by``/``top_n`` are inert there). The benchmark stays the index either way.
    """

    model_config = ConfigDict(extra="forbid")
    type: StrategyType = "factor_strategy"
    universe: Literal["NIFTY200"] = "NIFTY200"
    rules: BacktestRules
    symbols: list[str] | None = Field(
        default=None,
        description=f"custom_basket only: 1–{MAX_BASKET_SYMBOLS} tickers, held equal-weighted",
    )
    start: date
    end: date
    costs_bps: int = Field(default=0, ge=0, le=500)
    benchmark: str = Field(default="NIFTY200_TRI", min_length=1, max_length=40)

    @model_validator(mode="after")
    def _valid_range(self) -> BacktestSpec:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self

    @model_validator(mode="after")
    def _symbols_match_type(self) -> BacktestSpec:
        """``symbols`` is required by — and exclusive to — ``custom_basket``.

        Normalised in place (upper-cased, trimmed, de-duplicated keeping first-seen order) so the
        canonical spec, and therefore the reproducibility hash, does not depend on how it was typed.
        """
        if self.type == "factor_strategy":
            if self.symbols is not None:
                raise ValueError("symbols is only valid for a custom_basket backtest")
            return self

        raw = self.symbols or []
        cleaned: list[str] = []
        for s in raw:
            sym = s.strip().upper()
            if not sym:
                raise ValueError("symbols must not contain blank entries")
            if sym not in cleaned:
                cleaned.append(sym)
        if not cleaned:
            raise ValueError("custom_basket requires at least one symbol")
        if len(cleaned) > MAX_BASKET_SYMBOLS:
            raise ValueError(f"a custom_basket holds at most {MAX_BASKET_SYMBOLS} symbols")
        object.__setattr__(self, "symbols", cleaned)
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
    "MAX_BASKET_SYMBOLS",
    "BacktestListItem",
    "BacktestResponse",
    "BacktestRules",
    "BacktestSpec",
    "SubmitBacktestRequest",
]

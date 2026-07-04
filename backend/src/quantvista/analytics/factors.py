"""Factor framework (QV-028) — pluggable, PIT-only, bias-free by construction.

Each ``Factor`` reads a single raw value through the ``ScoringContext`` (PIT gateway) and returns
``float | None`` (None → unavailable → excluded downstream, ``05`` §2). Factors hold no session or
repo, so they cannot read "latest" data — the structural look-ahead defence (``05`` §1.1). New
factors plug in without touching the engine (Open/Closed); QV-029's engine reads ``ALL_FACTORS``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from quantvista.analytics.context import ScoringContext


class FactorCategory(StrEnum):
    FUNDAMENTAL = "fundamental"
    MOMENTUM = "momentum"
    QUALITY = "quality"
    SENTIMENT = "sentiment"  # no concrete factor yet — needs news data (Epic 5)
    RISK = "risk"


class Factor(ABC):
    """A single factor: raw value from PIT data, or None if unavailable."""

    key: ClassVar[str]
    category: ClassVar[FactorCategory]
    direction: ClassVar[int]  # +1 higher-is-better, -1 lower-is-better

    @abstractmethod
    def compute(self, ctx: ScoringContext, stock_id: UUID, as_of: date) -> float | None: ...


class _FundamentalFactor(Factor):
    """Reads one ratio from the PIT fundamentals version."""

    ratio: ClassVar[str]

    def compute(self, ctx: ScoringContext, stock_id: UUID, as_of: date) -> float | None:
        version = ctx.fundamentals_as_of(stock_id, as_of)
        if version is None:
            return None
        raw = version.ratios.get(self.ratio)
        return float(raw) if raw is not None else None


class _IndicatorFactor(Factor):
    """Reads one column from the PIT technical-indicator row."""

    column: ClassVar[str]

    def compute(self, ctx: ScoringContext, stock_id: UUID, as_of: date) -> float | None:
        indicators = ctx.indicator_as_of(stock_id, as_of)
        if indicators is None:
            return None
        raw = indicators.get(self.column)
        return float(raw) if raw is not None else None


# --- Fundamental --------------------------------------------------------------
class PEFactor(_FundamentalFactor):
    key = "pe"
    category = FactorCategory.FUNDAMENTAL
    direction = -1
    ratio = "pe"


class PBFactor(_FundamentalFactor):
    key = "pb"
    category = FactorCategory.FUNDAMENTAL
    direction = -1
    ratio = "pb"


# --- Quality ------------------------------------------------------------------
class ROEFactor(_FundamentalFactor):
    key = "roe"
    category = FactorCategory.QUALITY
    direction = 1
    ratio = "roe"


class ROCEFactor(_FundamentalFactor):
    key = "roce"
    category = FactorCategory.QUALITY
    direction = 1
    ratio = "roce"


class DebtEquityFactor(_FundamentalFactor):
    key = "debt_equity"
    category = FactorCategory.QUALITY
    direction = -1
    ratio = "debt_equity"


# --- Momentum -----------------------------------------------------------------
class Return3MFactor(_IndicatorFactor):
    key = "ret_3m"
    category = FactorCategory.MOMENTUM
    direction = 1
    column = "ret_3m"


class Return6MFactor(_IndicatorFactor):
    key = "ret_6m"
    category = FactorCategory.MOMENTUM
    direction = 1
    column = "ret_6m"


class Return12MFactor(_IndicatorFactor):
    key = "ret_12m"
    category = FactorCategory.MOMENTUM
    direction = 1
    column = "ret_12m"


# --- Risk (direction -1: lower is better) -------------------------------------
class BetaFactor(_IndicatorFactor):
    key = "beta"
    category = FactorCategory.RISK
    direction = -1
    column = "beta_1y"


class Vol30DFactor(_IndicatorFactor):
    key = "vol_30d"
    category = FactorCategory.RISK
    direction = -1
    column = "vol_30d"


ALL_FACTORS: tuple[Factor, ...] = (
    PEFactor(),
    PBFactor(),
    ROEFactor(),
    ROCEFactor(),
    DebtEquityFactor(),
    Return3MFactor(),
    Return6MFactor(),
    Return12MFactor(),
    BetaFactor(),
    Vol30DFactor(),
)

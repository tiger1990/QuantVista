"""Analytics published interfaces.

Depends on Market Data + News (through their interfaces only). Owns factors, the
scoring engine, and backtesting. Point-in-time correctness is non-negotiable here:
factors/scores/backtests may use only data knowable at ``as_of``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class IFactor(Protocol):
    """A single factor: ``compute`` returns a raw value or None (excluded)."""

    def compute(self, ctx: Any, stock_id: UUID, as_of: date) -> float | None: ...


@runtime_checkable
class IScoreEngine(Protocol):
    """Cross-sectional normalization + weighted composite score (0–100)."""

    def score(self, stock_id: UUID, as_of: date) -> float | None: ...


@runtime_checkable
class IBacktestEngine(Protocol):
    """Deterministic, reproducible backtest over a versioned spec."""

    def run(self, spec: dict[str, Any]) -> dict[str, Any]: ...

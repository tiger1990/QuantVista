"""Backtest engine seam (QV-062).

QV-062 ships only the async submit/poll plumbing. The **real** rebalance-loop compute (PIT data,
survivorship-free universe, frictions, metrics) is **QV-065** — this is a deliberate placeholder so
the queued→running→succeeded lifecycle works end-to-end today. ``BacktestEngine.run`` returns an
empty-but-valid result; QV-065 replaces the body (keeping this signature) to produce real metrics +
a stored result artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quantvista.schemas.backtest import BacktestSpec


@dataclass(frozen=True)
class BacktestResult:
    """Outcome of a backtest run: metrics (CAGR, vol, Sharpe, maxDD, …) + an artifact reference.

    ``result_ref`` is the object-store key for the full result artifact (realized in QV-067); the
    placeholder engine sets it to ``None``.
    """

    metrics: dict[str, Any] = field(default_factory=dict)
    result_ref: str | None = None


class BacktestEngine:
    """Runs a backtest spec into a result. **Placeholder** — QV-065 implements the real engine."""

    def run(self, spec: BacktestSpec) -> BacktestResult:
        # QV-065: build the PIT panel, run the rebalance loop with frictions, compute metrics, and
        # persist the artifact. Until then, return an empty-but-valid result so the lifecycle
        # completes and polling is demonstrable.
        return BacktestResult(metrics={}, result_ref=None)


__all__ = ["BacktestEngine", "BacktestResult"]

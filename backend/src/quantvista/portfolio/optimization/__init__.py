"""portfolio.optimization — allocation optimizers over a shared CVXPY engine.

``BaseCvxpyOptimizer`` (base) owns the execution engine + Decimal boundary; each optimizer supplies
only its formulation: ``MeanVarianceOptimizer`` (QV-054) and ``RiskParityOptimizer`` (QV-057). See
``base`` for the framework rationale (the QV-054-deferred extraction, now driven by a real second
consumer).
"""

from __future__ import annotations

from quantvista.portfolio.optimization.base import (
    Objective,
    OptimizationRequest,
    OptimizationResult,
)
from quantvista.portfolio.optimization.mean_variance import MeanVarianceOptimizer
from quantvista.portfolio.optimization.risk_parity import RiskParityOptimizer

__all__ = [
    "MeanVarianceOptimizer",
    "Objective",
    "OptimizationRequest",
    "OptimizationResult",
    "RiskParityOptimizer",
]

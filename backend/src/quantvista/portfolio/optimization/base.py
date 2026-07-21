"""portfolio.optimization — shared optimizer engine (QV-057 framework extraction).

QV-054 shipped a single ``MeanVarianceOptimizer`` with all CVXPY usage contained in one module and
deliberately deferred the framework extraction to "the first real second optimizer" (QV-057, Risk
Parity). This module is that extraction: ``BaseCvxpyOptimizer`` owns everything common to every
optimizer — annualizing μ/Σ from the PIT returns matrix, the structural ``feasibility`` pre-check,
the Decimal↔float weight round-trip, ``check`` validation, and the annualized result metrics — while
each concrete optimizer implements only its ``_solve`` (the mathematical *formulation*). This is the
QV-054-deferred "decouple the formulation from the CVXPY execution engine," now driven by a real
second consumer; a speculative *multi-backend* solver protocol stays deferred (still one backend).

Inputs/weights cross the Decimal↔float boundary explicitly: solve in float64, quantize weights back
to Decimal, re-normalize to Σw=1 within ``WEIGHT_SUM_EPSILON``, then validate. An infeasible problem
raises ``InfeasibleConstraints`` with the **binding** constraint (US-03), never a silent result.
Money on the wire is Decimal, never float.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from uuid import UUID

import numpy as np

from quantvista.market_data.returns import ReturnsMatrix
from quantvista.portfolio.constraints import (
    Allocation,
    ConstraintKind,
    ConstraintReport,
    Constraints,
    ConstraintStatus,
    InfeasibleConstraints,
    check,
    feasibility,
    raise_if_infeasible,
)
from quantvista.portfolio.covariance import (
    CovarianceEstimator,
    FloatMatrix,
    LedoitWolfEstimator,
)

_TRADING_DAYS = 252  # annualization factor for daily returns → annual μ / Σ
_WEIGHT_QUANTUM = Decimal("0.000001")  # numeric(9,6), matches portfolio_positions
_SOLVE_TOL = 1e-6


class Objective(Enum):
    MIN_VOL = "min_vol"
    TARGET_RETURN = "target_return"
    MAX_SHARPE = "max_sharpe"


@dataclass(frozen=True)
class OptimizationRequest:
    """What to optimize. ``sector_of`` maps stock → sector for the sector-cap constraints;
    ``covariance_estimator`` is pluggable (defaults to Ledoit-Wolf). Rates/targets annualized.
    ``objective`` is mean-variance-specific; risk parity ignores it (it always equalizes risk)."""

    objective: Objective
    constraints: Constraints
    risk_free_rate: Decimal = Decimal(0)
    sector_of: Mapping[UUID, str] = field(default_factory=dict)
    covariance_estimator: CovarianceEstimator = field(default_factory=LedoitWolfEstimator)


@dataclass(frozen=True)
class OptimizationResult:
    """Optimizer output. Weights are Decimal and sum to 1.0 (within ε); metrics are annualized."""

    weights: dict[UUID, Decimal]
    expected_return: Decimal
    expected_volatility: Decimal
    constraint_report: ConstraintReport


def sector_matrix(ids: tuple[UUID, ...], sector_of: Mapping[UUID, str], sector: str) -> FloatMatrix:
    """Row selector (1.0 where a name is in ``sector``) for the aggregate sector-cap constraint."""
    return np.array([1.0 if sector_of.get(sid) == sector else 0.0 for sid in ids], dtype=np.float64)


def sector_counts(ids: tuple[UUID, ...], sector_of: Mapping[UUID, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sid in ids:
        sector = sector_of.get(sid)
        if sector is not None:
            counts[sector] = counts.get(sector, 0) + 1
    return counts


def to_decimal_weights(
    ids: tuple[UUID, ...], raw: FloatMatrix, *, long_only: bool
) -> dict[UUID, Decimal]:
    """Quantize weights to Decimal(9,6); re-normalize so Σw = 1 exactly (residual → largest)."""
    cleaned = [max(0.0, float(x)) if long_only else float(x) for x in raw]
    weights = [Decimal(str(x)).quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_UP) for x in cleaned]
    residual = Decimal(1) - sum(weights, Decimal(0))
    i_max = max(range(len(weights)), key=lambda i: weights[i])
    weights[i_max] += residual  # absorb rounding dust so the book is exactly fully invested
    return dict(zip(ids, weights, strict=True))


class BaseCvxpyOptimizer(ABC):
    """Shared CVXPY execution engine; subclasses supply only the ``_solve`` formulation.

    The template ``optimize`` handles the parts every optimizer shares (μ/Σ, feasibility, the
    Decimal boundary, ``check`` validation, metrics); ``_solve`` returns the raw float weights (or
    ``None`` + solver status when the numeric problem is infeasible), and ``_diagnose`` names the
    binding constraint for that infeasible case. Implements the ``IOptimizer`` protocol.
    """

    def optimize(self, request: OptimizationRequest, returns: ReturnsMatrix) -> OptimizationResult:
        ids = returns.stock_ids
        n = len(ids)
        cons = request.constraints

        if n == 0 or returns.values.shape[0] < 2:
            raise InfeasibleConstraints(
                ConstraintStatus(
                    ConstraintKind.CARDINALITY,
                    satisfied=False,
                    detail="not enough assets/observations to optimize",
                    slack=Decimal(-1),
                )
            )

        # Annualized expected returns (historical mean) and covariance (shrinkage).
        mu = np.asarray(returns.values.mean(axis=0), dtype=np.float64) * _TRADING_DAYS
        sigma = request.covariance_estimator.estimate(returns.values) * _TRADING_DAYS

        # Structural pre-check (no μ/Σ needed) — catches unsatisfiable constraint sets up front.
        raise_if_infeasible(feasibility(cons, n, sector_counts(ids, request.sector_of)))

        weights_raw, _status = self._solve(mu, sigma, request, ids)
        if weights_raw is None:
            raise InfeasibleConstraints(self._diagnose(mu, sigma, request, ids))

        weights = to_decimal_weights(ids, weights_raw, long_only=cons.long_only)
        report = check(cons, Allocation(weights=weights, sector_of=request.sector_of))
        raise_if_infeasible(report)

        w_vec = np.array([float(weights[sid]) for sid in ids], dtype=np.float64)
        expected_return = Decimal(str(float(mu @ w_vec)))
        expected_volatility = Decimal(str(float(np.sqrt(w_vec @ sigma @ w_vec))))
        return OptimizationResult(
            weights=weights,
            expected_return=expected_return,
            expected_volatility=expected_volatility,
            constraint_report=report,
        )

    @abstractmethod
    def _solve(
        self,
        mu: FloatMatrix,
        sigma: FloatMatrix,
        request: OptimizationRequest,
        ids: tuple[UUID, ...],
    ) -> tuple[FloatMatrix | None, str]:
        """Build + solve the optimizer-specific CVXPY problem. Returns (raw weights | None, status).

        May raise ``InfeasibleConstraints`` directly for a formulation-level precondition (e.g. a
        missing required target). A ``None`` weights result means the numeric solve was infeasible.
        """

    def _diagnose(
        self,
        mu: FloatMatrix,
        sigma: FloatMatrix,
        request: OptimizationRequest,
        ids: tuple[UUID, ...],
    ) -> ConstraintStatus:
        """Name the binding constraint when the numeric solve is infeasible (structurals passed).

        Default: report a jointly-infeasible constraint set. Optimizers with a richer probe (e.g.
        mean-variance's max-achievable-return LP) override this.
        """
        return ConstraintStatus(
            ConstraintKind.FULL_INVESTMENT,
            satisfied=False,
            detail="constraints are jointly infeasible",
            slack=Decimal(-1),
        )


__all__ = [
    "BaseCvxpyOptimizer",
    "Objective",
    "OptimizationRequest",
    "OptimizationResult",
    "sector_matrix",
    "to_decimal_weights",
]

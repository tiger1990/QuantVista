"""portfolio — mean-variance optimizer (QV-054).

Markowitz mean-variance optimization over a convex QP (**CVXPY + OSQP**) with a stable
**Ledoit-Wolf** covariance (risk R7). Three objectives: ``MIN_VOL`` (min ``wᵀΣw``),
``TARGET_RETURN`` (min variance s.t. ``μᵀw ≥ target``), and ``MAX_SHARPE`` (max Sharpe via the
standard convex y=κw reformulation). Reuses QV-053: ``Constraints`` translate into CVXPY
constraints, the structural ``feasibility`` pre-check runs first, and the final Decimal allocation
is validated through ``check`` — an infeasible problem raises ``InfeasibleConstraints`` with the
**binding** constraint (US-03), never a silent/degenerate result.

CVXPY usage is deliberately contained in this one module so a solver abstraction can be extracted
later (Epic-7 framework expansion) without touching optimizer logic. Inputs/weights cross the
Decimal↔float boundary explicitly: solve in float64, quantize weights back to Decimal, re-normalize
to Σw=1 within ``WEIGHT_SUM_EPSILON``, then validate. Money on the wire is Decimal, never float.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from uuid import UUID

import cvxpy as cp
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
    ``covariance_estimator`` is pluggable (defaults to Ledoit-Wolf). Rates/targets annualized."""

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


def _sector_matrix(
    ids: tuple[UUID, ...], sector_of: Mapping[UUID, str], sector: str
) -> FloatMatrix:
    """Row selector (1.0 where a name is in ``sector``) for the aggregate sector-cap constraint."""
    return np.array([1.0 if sector_of.get(sid) == sector else 0.0 for sid in ids], dtype=np.float64)


def _sector_counts(ids: tuple[UUID, ...], sector_of: Mapping[UUID, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sid in ids:
        sector = sector_of.get(sid)
        if sector is not None:
            counts[sector] = counts.get(sector, 0) + 1
    return counts


def _base_constraints(
    w: cp.Variable, cons: Constraints, ids: tuple[UUID, ...], sector_of: Mapping[UUID, str]
) -> list[cp.Constraint]:
    """Linear constraints shared by MIN_VOL / TARGET_RETURN (full investment added by caller)."""
    out: list[cp.Constraint] = []
    if cons.long_only:
        out.append(w >= 0)
    if cons.max_weight is not None:
        out.append(w <= float(cons.max_weight))
    for sector, cap in cons.sector_caps.items():
        out.append(_sector_matrix(ids, sector_of, sector) @ w <= float(cap))
    return out


def _solve_min_variance(
    mu: FloatMatrix,
    sigma: FloatMatrix,
    cons: Constraints,
    ids: tuple[UUID, ...],
    sector_of: Mapping[UUID, str],
    *,
    return_floor: float | None,
) -> tuple[FloatMatrix | None, str]:
    """Minimize variance s.t. full investment + linear constraints (+ optional floor / vol cap)."""
    n = len(ids)
    w = cp.Variable(n)
    constraints = [cp.sum(w) == 1, *_base_constraints(w, cons, ids, sector_of)]
    if return_floor is not None:
        constraints.append(mu @ w >= return_floor)
    # A volatility cap is a *quadratic* (second-order-cone) constraint that OSQP (a pure QP solver)
    # can't take — route those problems to Clarabel, a conic solver bundled with cvxpy.
    solver = cp.OSQP
    if cons.target_volatility is not None:
        constraints.append(
            cp.quad_form(w, cp.psd_wrap(sigma)) <= float(cons.target_volatility) ** 2
        )
        solver = cp.CLARABEL
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))), constraints)
    prob.solve(solver=solver)
    if prob.status != cp.OPTIMAL or w.value is None:
        return None, prob.status
    return np.asarray(w.value, dtype=np.float64), prob.status


def _solve_max_sharpe(
    mu: FloatMatrix,
    sigma: FloatMatrix,
    cons: Constraints,
    ids: tuple[UUID, ...],
    sector_of: Mapping[UUID, str],
    risk_free_rate: float,
) -> tuple[FloatMatrix | None, str]:
    """Max Sharpe via the convex y=κw homogenization (long-only). Recovers ``w = y / Σy``."""
    n = len(ids)
    y = cp.Variable(n)
    kappa = cp.Variable(nonneg=True)
    excess = mu - risk_free_rate
    constraints = [excess @ y == 1, cp.sum(y) == kappa]
    if cons.long_only:
        constraints.append(y >= 0)
    if cons.max_weight is not None:
        constraints.append(y <= kappa * float(cons.max_weight))
    for sector, cap in cons.sector_caps.items():
        constraints.append(_sector_matrix(ids, sector_of, sector) @ y <= kappa * float(cap))
    prob = cp.Problem(cp.Minimize(cp.quad_form(y, cp.psd_wrap(sigma))), constraints)
    prob.solve(solver=cp.OSQP)
    if (
        prob.status != cp.OPTIMAL
        or y.value is None
        or kappa.value is None
        or kappa.value <= _SOLVE_TOL
    ):
        return None, prob.status
    return np.asarray(y.value, dtype=np.float64) / float(kappa.value), prob.status


def _max_achievable_return(
    mu: FloatMatrix, cons: Constraints, ids: tuple[UUID, ...], sector_of: Mapping[UUID, str]
) -> float | None:
    """LP: the highest ``μᵀw`` reachable under the non-return constraints (infeasibility probe)."""
    n = len(ids)
    w = cp.Variable(n)
    constraints = [cp.sum(w) == 1, *_base_constraints(w, cons, ids, sector_of)]
    prob = cp.Problem(cp.Maximize(mu @ w), constraints)
    prob.solve(solver=cp.OSQP)
    if prob.status != cp.OPTIMAL or w.value is None:
        return None
    return float(mu @ np.asarray(w.value, dtype=np.float64))


def _diagnose_infeasible(
    mu: FloatMatrix, cons: Constraints, ids: tuple[UUID, ...], sector_of: Mapping[UUID, str]
) -> ConstraintStatus:
    """Identify the binding constraint when the numeric solve is infeasible (structurals passed)."""
    if cons.target_return is not None:
        reachable = _max_achievable_return(mu, cons, ids, sector_of)
        target = float(cons.target_return)
        if reachable is None or reachable < target:
            shown = "n/a" if reachable is None else f"{reachable:.4f}"
            return ConstraintStatus(
                ConstraintKind.TARGET_RETURN,
                satisfied=False,
                detail=f"max achievable return {shown} < target {cons.target_return}",
                slack=Decimal(-1),
            )
    if cons.target_volatility is not None:
        return ConstraintStatus(
            ConstraintKind.TARGET_VOLATILITY,
            satisfied=False,
            detail=f"target volatility {cons.target_volatility} not reachable under constraints",
            slack=Decimal(-1),
        )
    return ConstraintStatus(
        ConstraintKind.FULL_INVESTMENT,
        satisfied=False,
        detail="constraints are jointly infeasible",
        slack=Decimal(-1),
    )


def _to_decimal_weights(
    ids: tuple[UUID, ...], raw: FloatMatrix, *, long_only: bool
) -> dict[UUID, Decimal]:
    """Quantize weights to Decimal(9,6); re-normalize so Σw = 1 exactly (residual → largest)."""
    cleaned = [max(0.0, float(x)) if long_only else float(x) for x in raw]
    weights = [Decimal(str(x)).quantize(_WEIGHT_QUANTUM, rounding=ROUND_HALF_UP) for x in cleaned]
    residual = Decimal(1) - sum(weights, Decimal(0))
    i_max = max(range(len(weights)), key=lambda i: weights[i])
    weights[i_max] += residual  # absorb rounding dust so the book is exactly fully invested
    return dict(zip(ids, weights, strict=True))


class MeanVarianceOptimizer:
    """Markowitz optimizer (CVXPY+OSQP, Ledoit-Wolf covariance); implements ``IOptimizer``."""

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
        raise_if_infeasible(feasibility(cons, n, _sector_counts(ids, request.sector_of)))

        if request.objective is Objective.TARGET_RETURN and cons.target_return is None:
            raise InfeasibleConstraints(
                ConstraintStatus(
                    ConstraintKind.TARGET_RETURN,
                    satisfied=False,
                    detail="TARGET_RETURN objective requires constraints.target_return",
                    slack=Decimal(-1),
                )
            )

        if request.objective is Objective.MAX_SHARPE:
            weights_raw, _status = _solve_max_sharpe(
                mu, sigma, cons, ids, request.sector_of, float(request.risk_free_rate)
            )
        else:
            # A return floor applies whenever target_return is set (it's a constraint), regardless
            # of objective; MIN_VOL without a target simply minimizes variance.
            floor = float(cons.target_return) if cons.target_return is not None else None
            weights_raw, _status = _solve_min_variance(
                mu, sigma, cons, ids, request.sector_of, return_floor=floor
            )

        if weights_raw is None:
            raise InfeasibleConstraints(_diagnose_infeasible(mu, cons, ids, request.sector_of))

        weights = _to_decimal_weights(ids, weights_raw, long_only=cons.long_only)
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


__all__ = [
    "MeanVarianceOptimizer",
    "Objective",
    "OptimizationRequest",
    "OptimizationResult",
]

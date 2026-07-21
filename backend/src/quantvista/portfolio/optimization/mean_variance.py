"""portfolio.optimization — mean-variance optimizer (QV-054; onto the shared base in QV-057).

Markowitz mean-variance optimization over a convex QP (**CVXPY + OSQP**) with a stable
**Ledoit-Wolf** covariance (risk R7). Three objectives: ``MIN_VOL`` (min variance),
``TARGET_RETURN`` (min variance s.t. ``μᵀw ≥ target``), and ``MAX_SHARPE`` (max Sharpe via the
standard convex y=κw reformulation). Behavior is unchanged from QV-054 — this only moves plumbing to
``BaseCvxpyOptimizer``; ``_solve`` keeps the objective formulation and ``_diagnose`` the
max-achievable-return probe. Reuses QV-053: ``Constraints`` translate into CVXPY constraints, the
structural ``feasibility`` pre-check runs first (base), and the final Decimal allocation is checked
through ``check`` — an infeasible problem raises ``InfeasibleConstraints`` with the **binding**
constraint (US-03).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

import cvxpy as cp
import numpy as np

from quantvista.portfolio.constraints import (
    ConstraintKind,
    Constraints,
    ConstraintStatus,
    InfeasibleConstraints,
)
from quantvista.portfolio.covariance import FloatMatrix
from quantvista.portfolio.optimization.base import (
    _SOLVE_TOL,
    BaseCvxpyOptimizer,
    Objective,
    OptimizationRequest,
    sector_matrix,
)


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
        out.append(sector_matrix(ids, sector_of, sector) @ w <= float(cap))
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
        constraints.append(sector_matrix(ids, sector_of, sector) @ y <= kappa * float(cap))
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


class MeanVarianceOptimizer(BaseCvxpyOptimizer):
    """Markowitz optimizer (CVXPY+OSQP, Ledoit-Wolf covariance); implements ``IOptimizer``."""

    def _solve(
        self,
        mu: FloatMatrix,
        sigma: FloatMatrix,
        request: OptimizationRequest,
        ids: tuple[UUID, ...],
    ) -> tuple[FloatMatrix | None, str]:
        cons = request.constraints
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
            return _solve_max_sharpe(
                mu, sigma, cons, ids, request.sector_of, float(request.risk_free_rate)
            )
        # A return floor applies whenever target_return is set (it's a constraint), regardless of
        # objective; MIN_VOL without a target simply minimizes variance.
        floor = float(cons.target_return) if cons.target_return is not None else None
        return _solve_min_variance(mu, sigma, cons, ids, request.sector_of, return_floor=floor)

    def _diagnose(
        self,
        mu: FloatMatrix,
        sigma: FloatMatrix,
        request: OptimizationRequest,
        ids: tuple[UUID, ...],
    ) -> ConstraintStatus:
        """Identify the binding constraint when the numeric solve is infeasible (structurals ok)."""
        cons = request.constraints
        if cons.target_return is not None:
            reachable = _max_achievable_return(mu, cons, ids, request.sector_of)
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
                detail=f"target volatility {cons.target_volatility} not reachable",
                slack=Decimal(-1),
            )
        return ConstraintStatus(
            ConstraintKind.FULL_INVESTMENT,
            satisfied=False,
            detail="constraints are jointly infeasible",
            slack=Decimal(-1),
        )


__all__ = ["MeanVarianceOptimizer"]

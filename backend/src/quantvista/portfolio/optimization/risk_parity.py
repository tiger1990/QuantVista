"""portfolio.optimization — risk parity optimizer (QV-057).

Equal-risk-contribution allocation: choose weights so each holding contributes the same share of
portfolio risk (RCᵢ = wᵢ·(Σw)ᵢ, each ≈ 1/N of total), so no single name dominates risk — more robust
for retail than mean-variance, which chases estimated returns. Solved via the convex **log-barrier**
formulation (Spinu 2013 / Maillard et al.): ``min ½·wᵀΣw − (1/N)·Σ ln(wᵢ)`` over ``w > 0``; its
first-order condition ``wᵢ(Σw)ᵢ = 1/N`` is exactly equal risk contribution. The objective's ``log``
term is **not** a QP, so OSQP can't take it — solved with **Clarabel** (conic, bundled with cvxpy).
The un-normalized solution is scaled to ``Σw = 1``.

Shared QV-053 constraints that fit the homogeneous formulation are honored **in the solve**:
``long_only`` (inherent — risk parity needs ``w > 0``), ``max_weight`` and ``sector_caps`` enter as
linear constraints on the un-normalized ``w`` (``wᵢ ≤ max_weight·Σw``; ``Σ_{i∈s} wᵢ ≤ cap_s·Σw``),
which stay linear and survive normalization. Constraints not meaningful for pure risk parity —
``target_return`` / ``target_volatility`` / ``max_turnover`` / cardinality — are ignored (risk
parity has no return or vol target); the final Decimal allocation is still validated through shared
``check``. Structural infeasibility (e.g. ``max_weight`` below ``1/N``) is caught by the base's
``feasibility`` pre-check with the binding constraint (US-03).
"""

from __future__ import annotations

from uuid import UUID

import cvxpy as cp
import numpy as np

from quantvista.portfolio.covariance import FloatMatrix
from quantvista.portfolio.optimization.base import (
    _SOLVE_TOL,
    BaseCvxpyOptimizer,
    OptimizationRequest,
    sector_matrix,
)

_RP_FLOOR = 1e-8  # keep weights strictly positive for the log barrier's domain


class RiskParityOptimizer(BaseCvxpyOptimizer):
    """Equal-risk-contribution optimizer (CVXPY+Clarabel log-barrier); implements ``IOptimizer``."""

    def _solve(
        self,
        mu: FloatMatrix,
        sigma: FloatMatrix,
        request: OptimizationRequest,
        ids: tuple[UUID, ...],
    ) -> tuple[FloatMatrix | None, str]:
        # Risk parity ignores μ (no return target) and the objective/target constraints; it only
        # uses Σ and the box/sector caps that fit the homogeneous formulation.
        n = len(ids)
        cons = request.constraints
        w = cp.Variable(n, nonneg=True)
        total = cp.sum(w)
        constraints: list[cp.Constraint] = [w >= _RP_FLOOR]
        if cons.max_weight is not None:
            constraints.append(w <= float(cons.max_weight) * total)
        for sector, cap in cons.sector_caps.items():
            constraints.append(
                sector_matrix(ids, request.sector_of, sector) @ w <= float(cap) * total
            )
        objective = cp.Minimize(
            0.5 * cp.quad_form(w, cp.psd_wrap(sigma)) - (1.0 / n) * cp.sum(cp.log(w))
        )
        prob = cp.Problem(objective, constraints)
        prob.solve(solver=cp.CLARABEL)
        if prob.status != cp.OPTIMAL or w.value is None:
            return None, prob.status
        raw = np.asarray(w.value, dtype=np.float64)
        scale = float(raw.sum())
        if scale <= _SOLVE_TOL:
            return None, prob.status
        return raw / scale, prob.status  # normalize the homogeneous solution to Σw = 1


__all__ = ["RiskParityOptimizer"]

"""Unit tests for the mean-variance optimizer (portfolio.optimizer, QV-054) — synthetic data, no DB.

Covers each objective solving to optimal, weights summing to 1.0 as Decimal, QV-053 constraints
respected in the returned allocation, the max_sharpe result dominating on Sharpe, and the
infeasible → binding-constraint path (US-03). Returns matrices are synthesised in-process so the
optimizer is exercised without a database.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import numpy as np
import pytest

from quantvista.market_data.returns import ReturnsMatrix
from quantvista.portfolio.constraints import (
    Allocation,
    ConstraintKind,
    Constraints,
    InfeasibleConstraints,
    check,
)

# The optimizer imports cvxpy (the optional [portfolio] extra). Skip this module at collection where
# the extra isn't installed (e.g. the DB-only CI job) — the optimizer's own job installs it.
pytest.importorskip("cvxpy")

from quantvista.portfolio.optimization import (  # noqa: E402
    MeanVarianceOptimizer,
    Objective,
    OptimizationRequest,
    OptimizationResult,
)

_IDS = tuple(UUID(int=i + 1) for i in range(8))


def _returns(n: int = 250, seed: int = 0) -> ReturnsMatrix:
    rng = np.random.default_rng(seed)
    k = len(_IDS)
    factor = rng.standard_normal((n, 1))
    loadings = rng.uniform(0.4, 1.2, (1, k))
    drift = rng.uniform(0.0002, 0.0010, k)  # distinct per-asset means → non-degenerate μ
    noise = rng.standard_normal((n, k)) * 0.01
    values = factor @ loadings * 0.01 + noise + drift
    return ReturnsMatrix(values=values, stock_ids=_IDS, dates=(), dropped=())


def _sharpe(res: OptimizationResult) -> Decimal:
    return res.expected_return / res.expected_volatility


def test_min_vol_solves_and_sums_to_one() -> None:
    res = MeanVarianceOptimizer().optimize(
        OptimizationRequest(
            objective=Objective.MIN_VOL, constraints=Constraints(max_weight=Decimal("0.5"))
        ),
        _returns(),
    )
    assert all(isinstance(w, Decimal) for w in res.weights.values())
    assert sum(res.weights.values()) == pytest.approx(Decimal(1), abs=Decimal("0.0001"))
    assert check(Constraints(max_weight=Decimal("0.5")), _alloc(res)).feasible


def test_long_only_and_max_weight_respected() -> None:
    cons = Constraints(long_only=True, max_weight=Decimal("0.3"))
    res = MeanVarianceOptimizer().optimize(
        OptimizationRequest(objective=Objective.MIN_VOL, constraints=cons), _returns()
    )
    assert all(w >= Decimal(0) for w in res.weights.values())
    assert max(res.weights.values()) <= Decimal("0.3") + Decimal("0.0001")


def test_sector_caps_respected() -> None:
    sector_of = {sid: ("IT" if i < 4 else "FIN") for i, sid in enumerate(_IDS)}
    cons = Constraints(sector_caps={"IT": Decimal("0.4")})
    res = MeanVarianceOptimizer().optimize(
        OptimizationRequest(objective=Objective.MIN_VOL, constraints=cons, sector_of=sector_of),
        _returns(),
    )
    it_weight = sum(res.weights[sid] for i, sid in enumerate(_IDS) if i < 4)
    assert it_weight <= Decimal("0.4") + Decimal("0.0001")


def test_target_return_meets_floor() -> None:
    # pick a target between min-vol return and the max achievable
    base = MeanVarianceOptimizer().optimize(
        OptimizationRequest(objective=Objective.MIN_VOL, constraints=Constraints()), _returns()
    )
    target = base.expected_return + Decimal("0.01")
    cons = Constraints(target_return=target, max_weight=Decimal("0.5"))
    res = MeanVarianceOptimizer().optimize(
        OptimizationRequest(objective=Objective.TARGET_RETURN, constraints=cons), _returns()
    )
    assert res.expected_return >= target - Decimal("0.001")


def test_max_sharpe_dominates_other_objectives() -> None:
    r = _returns()
    cons = Constraints(max_weight=Decimal("0.5"))
    sharpe = MeanVarianceOptimizer().optimize(
        OptimizationRequest(objective=Objective.MAX_SHARPE, constraints=cons), r
    )
    minvol = MeanVarianceOptimizer().optimize(
        OptimizationRequest(objective=Objective.MIN_VOL, constraints=cons), r
    )
    assert _sharpe(sharpe) >= _sharpe(minvol) - Decimal("0.01")


def test_infeasible_target_return_reports_binding() -> None:
    cons = Constraints(
        target_return=Decimal("5.0"), max_weight=Decimal("0.3")
    )  # 500% — unreachable
    with pytest.raises(InfeasibleConstraints) as exc:
        MeanVarianceOptimizer().optimize(
            OptimizationRequest(objective=Objective.TARGET_RETURN, constraints=cons), _returns()
        )
    assert exc.value.binding.kind == ConstraintKind.TARGET_RETURN


def test_structurally_infeasible_max_weight_reports_binding() -> None:
    # max_weight 0.05 over 8 names → 0.40 < 1.0, can't be fully invested (structural)
    cons = Constraints(max_weight=Decimal("0.05"))
    with pytest.raises(InfeasibleConstraints) as exc:
        MeanVarianceOptimizer().optimize(
            OptimizationRequest(objective=Objective.MIN_VOL, constraints=cons), _returns()
        )
    assert exc.value.binding.kind == ConstraintKind.MAX_WEIGHT


def test_target_volatility_cap_respected() -> None:
    # cap the annualized vol; the solved portfolio must sit at or under it
    base = MeanVarianceOptimizer().optimize(
        OptimizationRequest(objective=Objective.MIN_VOL, constraints=Constraints()), _returns()
    )
    cap = base.expected_volatility * Decimal("1.5")  # comfortably reachable
    cons = Constraints(target_volatility=cap)
    res = MeanVarianceOptimizer().optimize(
        OptimizationRequest(objective=Objective.MIN_VOL, constraints=cons), _returns()
    )
    assert res.expected_volatility <= cap + Decimal("0.001")


def test_infeasible_target_volatility_reports_binding() -> None:
    # an absurdly low vol cap can't be met → binding TARGET_VOLATILITY
    cons = Constraints(target_volatility=Decimal("0.0001"))
    with pytest.raises(InfeasibleConstraints) as exc:
        MeanVarianceOptimizer().optimize(
            OptimizationRequest(objective=Objective.MIN_VOL, constraints=cons), _returns()
        )
    assert exc.value.binding.kind == ConstraintKind.TARGET_VOLATILITY


def test_empty_returns_matrix_is_infeasible() -> None:
    empty = ReturnsMatrix(values=np.empty((0, 0)), stock_ids=(), dates=(), dropped=())
    with pytest.raises(InfeasibleConstraints):
        MeanVarianceOptimizer().optimize(
            OptimizationRequest(objective=Objective.MIN_VOL, constraints=Constraints()), empty
        )


# --- helper: rebuild a QV-053 Allocation from a result to assert feasibility ---
def _alloc(res: OptimizationResult) -> Allocation:
    return Allocation(weights=res.weights)

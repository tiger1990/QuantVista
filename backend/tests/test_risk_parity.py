"""Unit tests for the risk-parity optimizer (QV-057).

Assert the defining property (equal risk contribution), the shared-constraint reuse (long-only,
max_weight, sector caps honored through the QV-053 ``check``), the Decimal boundary (Σw = 1), and
the infeasible→binding contract (US-03). cvxpy is the optional [portfolio] extra, so skip at
collection where it's absent (mirrors test_portfolio_optimizer).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import numpy as np
import pytest

from quantvista.market_data.returns import ReturnsMatrix
from quantvista.portfolio.constraints import Constraints, InfeasibleConstraints

pytest.importorskip("cvxpy")

from quantvista.portfolio.optimization import (  # noqa: E402
    Objective,
    OptimizationRequest,
    OptimizationResult,
    RiskParityOptimizer,
)

_IDS = tuple(UUID(int=i + 1) for i in range(6))


def _returns(n: int = 250, seed: int = 0) -> ReturnsMatrix:
    """Synthetic factor-model returns with distinct per-asset vols → non-degenerate Σ."""
    rng = np.random.default_rng(seed)
    k = len(_IDS)
    factor = rng.standard_normal((n, 1))
    loadings = rng.uniform(0.4, 1.4, (1, k))
    noise = rng.standard_normal((n, k)) * rng.uniform(0.008, 0.02, k)
    values = factor @ loadings * 0.01 + noise
    return ReturnsMatrix(values=values, stock_ids=_IDS, dates=(), dropped=())


def _request(cons: Constraints, sector_of: dict[UUID, str] | None = None) -> OptimizationRequest:
    # objective is mean-variance-specific; risk parity ignores it — any valid value is fine.
    return OptimizationRequest(
        objective=Objective.MIN_VOL, constraints=cons, sector_of=sector_of or {}
    )


def _risk_contributions(res: OptimizationResult, returns: ReturnsMatrix) -> np.ndarray:
    """Normalized per-asset risk contribution RCᵢ = wᵢ·(Σw)ᵢ / (wᵀΣw)."""
    cov = np.cov(returns.values, rowvar=False)
    w = np.array([float(res.weights[sid]) for sid in returns.stock_ids])
    rc = w * (cov @ w)
    return np.asarray(rc / rc.sum(), dtype=np.float64)


def test_equalizes_risk_contribution() -> None:
    returns = _returns()
    res = RiskParityOptimizer().optimize(_request(Constraints()), returns)
    rc = _risk_contributions(res, returns)
    target = 1.0 / len(_IDS)
    assert np.allclose(rc, target, atol=0.02), rc


def test_weights_sum_to_one_and_long_only() -> None:
    res = RiskParityOptimizer().optimize(_request(Constraints()), _returns())
    total = sum(res.weights.values())
    assert abs(total - Decimal(1)) <= Decimal("0.0001")
    assert all(w > 0 for w in res.weights.values())


def test_max_weight_respected() -> None:
    cons = Constraints(max_weight=Decimal("0.25"))
    res = RiskParityOptimizer().optimize(_request(cons), _returns())
    assert res.constraint_report.feasible
    assert max(res.weights.values()) <= Decimal("0.25") + Decimal("0.0001")


def test_sector_caps_respected() -> None:
    sector_of = {sid: ("A" if i < 3 else "B") for i, sid in enumerate(_IDS)}
    cons = Constraints(sector_caps={"A": Decimal("0.4")})
    res = RiskParityOptimizer().optimize(_request(cons, sector_of), _returns())
    assert res.constraint_report.feasible
    sector_a = sum(res.weights[sid] for i, sid in enumerate(_IDS) if i < 3)
    assert sector_a <= Decimal("0.4") + Decimal("0.0001")


def test_infeasible_max_weight_raises_binding() -> None:
    # max_weight below 1/N is structurally impossible (Σw=1 with N names) → binding MAX_WEIGHT.
    cons = Constraints(max_weight=Decimal("0.1"))  # 0.1 * 6 = 0.6 < 1
    with pytest.raises(InfeasibleConstraints) as exc:
        RiskParityOptimizer().optimize(_request(cons), _returns())
    assert exc.value.binding.kind.value == "max_weight"


def test_ignores_return_target() -> None:
    # Risk parity has no return target; setting one must not change the equal-RC solution.
    returns = _returns()
    plain = RiskParityOptimizer().optimize(_request(Constraints()), returns)
    with_target = RiskParityOptimizer().optimize(
        _request(Constraints(target_return=Decimal("5.0"))), returns
    )
    for sid in _IDS:
        assert abs(plain.weights[sid] - with_target.weights[sid]) <= Decimal("0.0001")

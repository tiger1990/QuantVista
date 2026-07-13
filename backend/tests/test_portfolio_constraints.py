"""Unit tests for the constraints engine (portfolio.constraints, QV-053) — pure, no DB.

Covers construction validation, per-constraint evaluation (satisfied + violated paths for every
kind), deterministic binding-constraint selection on infeasibility (US-03), the structural
feasibility pre-check, and the ``InfeasibleConstraints`` exception. Mirrors the pure-guard test
style of ``test_portfolio_services.py``.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

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

# --- deterministic stock ids for readable fixtures ---
A = UUID(int=1)
B = UUID(int=2)
C = UUID(int=3)
D = UUID(int=4)


def _status(report: ConstraintReport, kind: ConstraintKind) -> ConstraintStatus | None:
    return next((s for s in report.statuses if s.kind == kind), None)


# ---------------------------------------------------------------------------
# Task 1 — Constraints construction validation
# ---------------------------------------------------------------------------


def test_default_constraints_construct() -> None:
    c = Constraints()
    assert c.long_only is True
    assert c.min_weight == Decimal(0)
    assert c.max_weight is None
    assert dict(c.sector_caps) == {}


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-0.1"), Decimal("1.5")])
def test_max_weight_out_of_range_raises(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        Constraints(max_weight=bad)


def test_min_weight_above_max_weight_raises() -> None:
    with pytest.raises(ValueError):
        Constraints(max_weight=Decimal("0.2"), min_weight=Decimal("0.3"))


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("1.2"), Decimal("-0.1")])
def test_sector_cap_out_of_range_raises(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        Constraints(sector_caps={"IT": bad})


@pytest.mark.parametrize("bad", [Decimal("-0.1"), Decimal("1.1")])
def test_min_weight_out_of_range_raises(bad: Decimal) -> None:
    with pytest.raises(ValueError):
        Constraints(min_weight=bad)


def test_cardinality_min_below_one_raises() -> None:
    with pytest.raises(ValueError):
        Constraints(cardinality_min=0)


def test_cardinality_max_below_one_raises() -> None:
    with pytest.raises(ValueError):
        Constraints(cardinality_max=0)


def test_cardinality_min_above_max_raises() -> None:
    with pytest.raises(ValueError):
        Constraints(cardinality_min=5, cardinality_max=3)


def test_negative_turnover_raises() -> None:
    with pytest.raises(ValueError):
        Constraints(max_turnover=Decimal("-0.1"))


def test_non_positive_target_volatility_raises() -> None:
    with pytest.raises(ValueError):
        Constraints(target_volatility=Decimal("0"))


def test_sector_caps_are_immutable() -> None:
    src = {"IT": Decimal("0.25")}
    c = Constraints(sector_caps=src)
    src["IT"] = Decimal("0.99")  # mutating the source must not leak in
    assert c.sector_caps["IT"] == Decimal("0.25")
    with pytest.raises(TypeError):
        c.sector_caps["IT"] = Decimal("0.5")  # type: ignore[index]


# ---------------------------------------------------------------------------
# Task 3 — check(): per-constraint evaluation
# ---------------------------------------------------------------------------


def test_full_investment_satisfied() -> None:
    alloc = Allocation(weights={A: Decimal("0.5"), B: Decimal("0.5")})
    report = check(Constraints(), alloc)
    assert report.feasible is True
    assert report.binding is None
    fi = _status(report, ConstraintKind.FULL_INVESTMENT)
    assert fi is not None and fi.satisfied


def test_full_investment_violated_is_binding() -> None:
    alloc = Allocation(weights={A: Decimal("0.3"), B: Decimal("0.3")})  # sums to 0.6
    report = check(Constraints(), alloc)
    assert report.feasible is False
    assert report.binding is not None
    assert report.binding.kind == ConstraintKind.FULL_INVESTMENT


def test_full_investment_within_epsilon_ok() -> None:
    # 0.333334 * 3 = 1.000002, within WEIGHT_SUM_EPSILON
    alloc = Allocation(
        weights={A: Decimal("0.333334"), B: Decimal("0.333334"), C: Decimal("0.333334")}
    )
    report = check(Constraints(), alloc)
    assert report.feasible is True


def test_long_only_violated() -> None:
    alloc = Allocation(weights={A: Decimal("1.2"), B: Decimal("-0.2")})  # sums to 1.0
    report = check(Constraints(long_only=True), alloc)
    lo = _status(report, ConstraintKind.LONG_ONLY)
    assert lo is not None and not lo.satisfied
    assert report.feasible is False


def test_long_only_disabled_allows_negative() -> None:
    alloc = Allocation(weights={A: Decimal("1.2"), B: Decimal("-0.2")})
    report = check(Constraints(long_only=False), alloc)
    assert _status(report, ConstraintKind.LONG_ONLY) is None  # not evaluated when disabled


def test_max_weight_violated() -> None:
    alloc = Allocation(weights={A: Decimal("0.6"), B: Decimal("0.4")})
    report = check(Constraints(max_weight=Decimal("0.5")), alloc)
    mw = _status(report, ConstraintKind.MAX_WEIGHT)
    assert mw is not None and not mw.satisfied
    assert report.binding is not None and report.binding.kind == ConstraintKind.MAX_WEIGHT


def test_max_weight_satisfied() -> None:
    alloc = Allocation(weights={A: Decimal("0.5"), B: Decimal("0.5")})
    report = check(Constraints(max_weight=Decimal("0.5")), alloc)
    mw = _status(report, ConstraintKind.MAX_WEIGHT)
    assert mw is not None and mw.satisfied


def test_min_weight_violated() -> None:
    # smallest held name (0.02) is below the 0.05 floor
    alloc = Allocation(weights={A: Decimal("0.98"), B: Decimal("0.02")})
    report = check(Constraints(min_weight=Decimal("0.05")), alloc)
    mw = _status(report, ConstraintKind.MIN_WEIGHT)
    assert mw is not None and not mw.satisfied


def test_min_weight_ignores_zero_weight_holdings() -> None:
    # B at exactly 0 is "not held" and exempt from the floor
    alloc = Allocation(weights={A: Decimal("1.0"), B: Decimal("0")})
    report = check(Constraints(min_weight=Decimal("0.05")), alloc)
    mw = _status(report, ConstraintKind.MIN_WEIGHT)
    assert mw is not None and mw.satisfied


def test_sector_cap_violated() -> None:
    alloc = Allocation(
        weights={A: Decimal("0.4"), B: Decimal("0.4"), C: Decimal("0.2")},
        sector_of={A: "IT", B: "IT", C: "FIN"},
    )
    report = check(Constraints(sector_caps={"IT": Decimal("0.5")}), alloc)  # IT = 0.8 > 0.5
    sc = _status(report, ConstraintKind.SECTOR_CAP)
    assert sc is not None and not sc.satisfied
    assert "IT" in sc.detail


def test_sector_cap_satisfied() -> None:
    alloc = Allocation(
        weights={A: Decimal("0.3"), B: Decimal("0.2"), C: Decimal("0.5")},
        sector_of={A: "IT", B: "IT", C: "FIN"},
    )
    report = check(Constraints(sector_caps={"IT": Decimal("0.5")}), alloc)  # IT = 0.5 == cap
    sc = _status(report, ConstraintKind.SECTOR_CAP)
    assert sc is not None and sc.satisfied


def test_cardinality_max_violated() -> None:
    alloc = Allocation(
        weights={A: Decimal("0.25"), B: Decimal("0.25"), C: Decimal("0.25"), D: Decimal("0.25")}
    )
    report = check(Constraints(cardinality_max=3), alloc)  # 4 holdings > 3
    card = _status(report, ConstraintKind.CARDINALITY)
    assert card is not None and not card.satisfied


def test_cardinality_min_violated() -> None:
    alloc = Allocation(weights={A: Decimal("0.6"), B: Decimal("0.4")})
    report = check(Constraints(cardinality_min=3), alloc)  # only 2 holdings < 3
    card = _status(report, ConstraintKind.CARDINALITY)
    assert card is not None and not card.satisfied


def test_cardinality_counts_only_nonzero() -> None:
    alloc = Allocation(weights={A: Decimal("0.5"), B: Decimal("0.5"), C: Decimal("0")})
    report = check(Constraints(cardinality_max=2), alloc)  # C is zero → 2 holdings, ok
    card = _status(report, ConstraintKind.CARDINALITY)
    assert card is not None and card.satisfied


def test_turnover_violated_with_prior() -> None:
    prior = {A: Decimal("1.0"), B: Decimal("0")}
    alloc = Allocation(
        weights={A: Decimal("0"), B: Decimal("1.0")}, prior_weights=prior
    )  # one-way turnover = 1.0
    report = check(Constraints(max_turnover=Decimal("0.3")), alloc)
    to = _status(report, ConstraintKind.TURNOVER)
    assert to is not None and not to.satisfied


def test_turnover_satisfied_with_prior() -> None:
    prior = {A: Decimal("0.5"), B: Decimal("0.5")}
    alloc = Allocation(
        weights={A: Decimal("0.55"), B: Decimal("0.45")}, prior_weights=prior
    )  # turnover = 0.05
    report = check(Constraints(max_turnover=Decimal("0.3")), alloc)
    to = _status(report, ConstraintKind.TURNOVER)
    assert to is not None and to.satisfied


def test_turnover_skipped_without_prior() -> None:
    alloc = Allocation(weights={A: Decimal("0.5"), B: Decimal("0.5")})  # no prior_weights
    report = check(Constraints(max_turnover=Decimal("0.3")), alloc)
    assert _status(report, ConstraintKind.TURNOVER) is None  # not applicable → not evaluated


def test_target_volatility_violated() -> None:
    alloc = Allocation(
        weights={A: Decimal("0.5"), B: Decimal("0.5")}, portfolio_volatility=Decimal("0.25")
    )
    report = check(Constraints(target_volatility=Decimal("0.18")), alloc)
    tv = _status(report, ConstraintKind.TARGET_VOLATILITY)
    assert tv is not None and not tv.satisfied


def test_target_volatility_skipped_when_metric_missing() -> None:
    alloc = Allocation(weights={A: Decimal("0.5"), B: Decimal("0.5")})  # no portfolio_volatility
    report = check(Constraints(target_volatility=Decimal("0.18")), alloc)
    assert _status(report, ConstraintKind.TARGET_VOLATILITY) is None


def test_target_return_violated() -> None:
    alloc = Allocation(
        weights={A: Decimal("0.5"), B: Decimal("0.5")}, portfolio_return=Decimal("0.05")
    )
    report = check(Constraints(target_return=Decimal("0.12")), alloc)  # 0.05 < 0.12 floor
    tr = _status(report, ConstraintKind.TARGET_RETURN)
    assert tr is not None and not tr.satisfied


def test_target_return_satisfied() -> None:
    alloc = Allocation(
        weights={A: Decimal("0.5"), B: Decimal("0.5")}, portfolio_return=Decimal("0.15")
    )
    report = check(Constraints(target_return=Decimal("0.12")), alloc)
    tr = _status(report, ConstraintKind.TARGET_RETURN)
    assert tr is not None and tr.satisfied


# ---------------------------------------------------------------------------
# Task 3 — binding-constraint determinism (US-03)
# ---------------------------------------------------------------------------


def test_binding_is_most_violated() -> None:
    # max_weight breached slightly (0.52 vs 0.5); sector cap breached hard (IT 0.9 vs 0.3)
    alloc = Allocation(
        weights={A: Decimal("0.52"), B: Decimal("0.38"), C: Decimal("0.10")},
        sector_of={A: "IT", B: "IT", C: "FIN"},  # IT = 0.90
    )
    cons = Constraints(max_weight=Decimal("0.5"), sector_caps={"IT": Decimal("0.3")})
    report = check(cons, alloc)
    assert report.feasible is False
    assert report.binding is not None
    assert report.binding.kind == ConstraintKind.SECTOR_CAP  # the worst offender wins


def test_binding_selection_is_deterministic() -> None:
    alloc = Allocation(weights={A: Decimal("0.7"), B: Decimal("0.7")})  # sum 1.4, max 0.7
    cons = Constraints(max_weight=Decimal("0.5"))
    first = check(cons, alloc).binding
    second = check(cons, alloc).binding
    assert first is not None and second is not None
    assert first.kind == second.kind  # same input → same binding, always


# ---------------------------------------------------------------------------
# Task 4 — feasibility(): structural pre-check
# ---------------------------------------------------------------------------


def test_feasibility_ok() -> None:
    report = feasibility(
        Constraints(max_weight=Decimal("0.2")),
        universe_size=10,
        sector_universe={"IT": 5, "FIN": 5},
    )
    assert report.feasible is True
    assert report.binding is None


def test_feasibility_cardinality_min_exceeds_universe() -> None:
    report = feasibility(
        Constraints(cardinality_min=20), universe_size=10, sector_universe={"IT": 10}
    )
    assert report.feasible is False
    assert report.binding is not None and report.binding.kind == ConstraintKind.CARDINALITY


def test_feasibility_max_weight_cannot_reach_full_investment() -> None:
    # max_weight 0.05 across at most 10 names → 0.5 < 1.0, impossible to be fully invested
    report = feasibility(
        Constraints(max_weight=Decimal("0.05")), universe_size=10, sector_universe={"IT": 10}
    )
    assert report.feasible is False
    assert report.binding is not None and report.binding.kind == ConstraintKind.MAX_WEIGHT


def test_feasibility_min_weight_forces_over_allocation() -> None:
    # 5 names each ≥ 0.30 → min total 1.5 > 1.0
    report = feasibility(
        Constraints(min_weight=Decimal("0.30"), cardinality_min=5),
        universe_size=10,
        sector_universe={"IT": 10},
    )
    assert report.feasible is False
    assert report.binding is not None and report.binding.kind == ConstraintKind.MIN_WEIGHT


def test_feasibility_sector_caps_under_sum() -> None:
    # every sector capped, caps sum to 0.6 < 1.0 → cannot be fully invested
    report = feasibility(
        Constraints(sector_caps={"IT": Decimal("0.3"), "FIN": Decimal("0.3")}),
        universe_size=10,
        sector_universe={"IT": 5, "FIN": 5},
    )
    assert report.feasible is False
    assert report.binding is not None and report.binding.kind == ConstraintKind.SECTOR_CAP


def test_feasibility_uncapped_sector_absorbs_remainder() -> None:
    # FIN is uncapped → it can absorb whatever IT's cap leaves; feasible
    report = feasibility(
        Constraints(sector_caps={"IT": Decimal("0.3")}),
        universe_size=10,
        sector_universe={"IT": 5, "FIN": 5},
    )
    assert report.feasible is True


# ---------------------------------------------------------------------------
# Task 5 — InfeasibleConstraints + raise_if_infeasible
# ---------------------------------------------------------------------------


def test_raise_if_infeasible_raises_on_violation() -> None:
    alloc = Allocation(weights={A: Decimal("0.3"), B: Decimal("0.3")})  # under-invested
    report = check(Constraints(), alloc)
    with pytest.raises(InfeasibleConstraints) as exc:
        raise_if_infeasible(report)
    assert exc.value.binding is not None
    assert exc.value.binding.kind == ConstraintKind.FULL_INVESTMENT


def test_raise_if_infeasible_noop_when_feasible() -> None:
    alloc = Allocation(weights={A: Decimal("0.5"), B: Decimal("0.5")})
    report = check(Constraints(), alloc)
    raise_if_infeasible(report)  # must not raise


def test_infeasible_constraints_carries_binding_detail() -> None:
    alloc = Allocation(weights={A: Decimal("0.9"), B: Decimal("0.4")}, sector_of={A: "IT", B: "IT"})
    report = check(Constraints(max_weight=Decimal("0.5")), alloc)
    exc = InfeasibleConstraints(report.binding)  # type: ignore[arg-type]
    assert report.binding is not None
    assert report.binding.detail in str(exc)


def test_unused_import_guard() -> None:
    # uuid4 is available for callers building ad-hoc fixtures; sanity that ids are distinct
    assert uuid4() != uuid4()

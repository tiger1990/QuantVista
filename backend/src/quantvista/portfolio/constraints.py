"""portfolio — constraints engine (QV-053).

A pure, optimizer-agnostic constraint model and evaluator shared by every optimizer
(Mean-Variance QV-054, Risk-Parity QV-057, HRP/Black-Litterman later) and the backtester
(QV-064). No DB, no API, no matrix math — scalar ``Decimal`` logic only, so it unit-tests
without a session (mirrors ``portfolio.services.enforce_portfolio_limit``).

An infeasible allocation or constraint set reports its **binding** constraint (US-03),
selected deterministically (most-violated by normalized magnitude; ties broken by
``ConstraintKind`` declaration order) so the message is reproducible for the UI and tests.
``check`` and ``feasibility`` *return* a :class:`ConstraintReport`; ``raise_if_infeasible``
raises :class:`InfeasibleConstraints` for callers (the QV-055 optimize API) that map it to
the canonical ``infeasible`` (422) envelope. No HTTP concerns live here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from uuid import UUID

from quantvista.portfolio.services import WEIGHT_SUM_EPSILON

_ZERO = Decimal(0)
_ONE = Decimal(1)


class ConstraintKind(Enum):
    """Constraint categories.

    Declaration order **is** the deterministic tie-break priority for binding-constraint
    selection: when two violations have equal normalized magnitude, the one declared first wins.
    """

    MAX_WEIGHT = "max_weight"
    MIN_WEIGHT = "min_weight"
    LONG_ONLY = "long_only"
    SECTOR_CAP = "sector_cap"
    CARDINALITY = "cardinality"
    TARGET_VOLATILITY = "target_volatility"
    TARGET_RETURN = "target_return"
    TURNOVER = "turnover"
    FULL_INVESTMENT = "full_investment"


@dataclass(frozen=True)
class Constraints:
    """Immutable allocation rules shared across optimizers.

    Full investment (``Σw = 1 ± WEIGHT_SUM_EPSILON``) is an always-on invariant, not a field.
    All weight/target fields are ``Decimal`` (never ``float``). Field bounds are validated at
    construction; nonsense raises ``ValueError``.
    """

    max_weight: Decimal | None = None
    min_weight: Decimal = _ZERO
    long_only: bool = True
    sector_caps: Mapping[str, Decimal] = field(default_factory=dict)
    cardinality_min: int | None = None
    cardinality_max: int | None = None
    target_volatility: Decimal | None = None
    target_return: Decimal | None = None
    max_turnover: Decimal | None = None

    def __post_init__(self) -> None:
        if self.max_weight is not None and not (_ZERO < self.max_weight <= _ONE):
            raise ValueError(f"max_weight must be in (0, 1], got {self.max_weight}")
        if not (_ZERO <= self.min_weight <= _ONE):
            raise ValueError(f"min_weight must be in [0, 1], got {self.min_weight}")
        if self.max_weight is not None and self.min_weight > self.max_weight:
            raise ValueError(f"min_weight {self.min_weight} exceeds max_weight {self.max_weight}")
        for sector, cap in self.sector_caps.items():
            if not (_ZERO < cap <= _ONE):
                raise ValueError(f"sector cap for {sector!r} must be in (0, 1], got {cap}")
        if self.cardinality_min is not None and self.cardinality_min < 1:
            raise ValueError(f"cardinality_min must be >= 1, got {self.cardinality_min}")
        if self.cardinality_max is not None and self.cardinality_max < 1:
            raise ValueError(f"cardinality_max must be >= 1, got {self.cardinality_max}")
        if (
            self.cardinality_min is not None
            and self.cardinality_max is not None
            and self.cardinality_min > self.cardinality_max
        ):
            raise ValueError(
                f"cardinality_min {self.cardinality_min} exceeds "
                f"cardinality_max {self.cardinality_max}"
            )
        if self.target_volatility is not None and self.target_volatility <= _ZERO:
            raise ValueError(f"target_volatility must be > 0, got {self.target_volatility}")
        if self.max_turnover is not None and self.max_turnover < _ZERO:
            raise ValueError(f"max_turnover must be >= 0, got {self.max_turnover}")
        # Freeze sector_caps into a read-only copy so the source dict can't leak in later.
        object.__setattr__(self, "sector_caps", MappingProxyType(dict(self.sector_caps)))


@dataclass(frozen=True)
class Allocation:
    """A candidate allocation to evaluate.

    ``portfolio_volatility``/``portfolio_return`` are supplied by the optimizer when the
    corresponding target is active; when absent, that target check is skipped (not failed).
    ``prior_weights`` (last allocation) is needed for the turnover check; absent → turnover skipped.
    """

    weights: Mapping[UUID, Decimal]
    sector_of: Mapping[UUID, str] = field(default_factory=dict)
    prior_weights: Mapping[UUID, Decimal] | None = None
    portfolio_volatility: Decimal | None = None
    portfolio_return: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        object.__setattr__(self, "sector_of", MappingProxyType(dict(self.sector_of)))
        if self.prior_weights is not None:
            object.__setattr__(self, "prior_weights", MappingProxyType(dict(self.prior_weights)))


@dataclass(frozen=True)
class ConstraintStatus:
    """The outcome for one constraint. ``slack`` is normalized: >= 0 satisfied, < 0 violated."""

    kind: ConstraintKind
    satisfied: bool
    detail: str
    slack: Decimal | None = None


@dataclass(frozen=True)
class ConstraintReport:
    """Aggregate result. ``binding is None`` iff ``feasible`` is True."""

    feasible: bool
    statuses: tuple[ConstraintStatus, ...]
    binding: ConstraintStatus | None


class InfeasibleConstraints(Exception):
    """Raised (by ``raise_if_infeasible``) when a report is infeasible; carries the binding status.

    Consumers (the QV-055 optimize API) map this to ``error.code = "infeasible"`` (422) with
    ``binding.detail`` in the message. No HTTP status is assigned here.
    """

    def __init__(self, binding: ConstraintStatus) -> None:
        self.binding = binding
        super().__init__(f"infeasible: {binding.detail}")


def _normalized_slack(actual: Decimal, limit: Decimal, *, ceiling: bool) -> Decimal:
    """Signed slack normalized by the limit's magnitude.

    ``ceiling`` True → ceiling: slack = (limit - actual) / |limit|.
    ``ceiling`` False → floor: slack = (actual - limit) / |limit|.
    Positive = room to spare; negative = violation magnitude.
    """
    base = abs(limit) if limit != _ZERO else _ONE
    return (limit - actual) / base if ceiling else (actual - limit) / base


def _held(weights: Mapping[UUID, Decimal]) -> list[Decimal]:
    """Weights of names actually held (strictly above the sum epsilon)."""
    return [w for w in weights.values() if w > WEIGHT_SUM_EPSILON]


def _pick_binding(statuses: tuple[ConstraintStatus, ...]) -> ConstraintStatus | None:
    """The most-violated status (most-negative normalized slack); ties broken by kind order."""
    order = {kind: i for i, kind in enumerate(ConstraintKind)}
    violated = [s for s in statuses if not s.satisfied]
    if not violated:
        return None
    return min(violated, key=lambda s: (s.slack if s.slack is not None else _ZERO, order[s.kind]))


def check(constraints: Constraints, allocation: Allocation) -> ConstraintReport:
    """Evaluate ``allocation`` against every active constraint → a per-constraint report.

    Only *active* constraints emit a status (e.g. turnover is skipped without ``prior_weights``,
    a target is skipped when its portfolio metric is ``None``). ``feasible`` is the AND of all
    emitted statuses; on infeasibility ``binding`` names the deterministic worst offender.
    """
    weights = allocation.weights
    statuses: list[ConstraintStatus] = []

    # MAX_WEIGHT — the largest holding may not exceed the per-name cap.
    if constraints.max_weight is not None and weights:
        cap = constraints.max_weight
        top = max(weights.values())
        statuses.append(
            ConstraintStatus(
                ConstraintKind.MAX_WEIGHT,
                satisfied=top <= cap + WEIGHT_SUM_EPSILON,
                detail=f"largest holding weight {top} vs max_weight {cap}",
                slack=_normalized_slack(top, cap, ceiling=True),
            )
        )

    # MIN_WEIGHT — every *held* name must clear the floor (zero-weight names are exempt).
    if constraints.min_weight > _ZERO:
        floor = constraints.min_weight
        held = _held(weights)
        smallest = min(held) if held else floor  # no holdings → trivially satisfied
        statuses.append(
            ConstraintStatus(
                ConstraintKind.MIN_WEIGHT,
                satisfied=smallest >= floor - WEIGHT_SUM_EPSILON,
                detail=f"smallest held weight {smallest} vs min_weight {floor}",
                slack=_normalized_slack(floor, smallest, ceiling=True),
            )
        )

    # LONG_ONLY — no negative weights.
    if constraints.long_only and weights:
        lowest = min(weights.values())
        statuses.append(
            ConstraintStatus(
                ConstraintKind.LONG_ONLY,
                satisfied=lowest >= -WEIGHT_SUM_EPSILON,
                detail=f"most-negative weight {lowest} (long-only requires >= 0)",
                slack=lowest,  # already a weight fraction; negative = violation magnitude
            )
        )

    # SECTOR_CAP — aggregate weight per sector may not exceed its cap; report the worst sector.
    if constraints.sector_caps:
        agg: dict[str, Decimal] = {}
        for stock_id, weight in weights.items():
            sector = allocation.sector_of.get(stock_id)
            if sector is not None:
                agg[sector] = agg.get(sector, _ZERO) + weight
        worst_slack = _ONE
        worst_sector = ""
        worst_total = _ZERO
        for sector, cap in constraints.sector_caps.items():
            total = agg.get(sector, _ZERO)
            slack = _normalized_slack(total, cap, ceiling=True)
            if slack < worst_slack:
                worst_slack, worst_sector, worst_total = slack, sector, total
        cap = constraints.sector_caps[worst_sector]
        statuses.append(
            ConstraintStatus(
                ConstraintKind.SECTOR_CAP,
                satisfied=worst_slack >= _ZERO,
                detail=f"sector {worst_sector!r} weight {worst_total} vs cap {cap}",
                slack=worst_slack,
            )
        )

    # CARDINALITY — number of held names within [min, max].
    if constraints.cardinality_min is not None or constraints.cardinality_max is not None:
        count = len(_held(weights))
        lo, hi = constraints.cardinality_min, constraints.cardinality_max
        if lo is not None and count < lo:
            satisfied, slack = False, _normalized_slack(Decimal(lo), Decimal(count), ceiling=True)
        elif hi is not None and count > hi:
            satisfied, slack = False, _normalized_slack(Decimal(count), Decimal(hi), ceiling=True)
        else:
            satisfied, slack = True, _ONE
        statuses.append(
            ConstraintStatus(
                ConstraintKind.CARDINALITY,
                satisfied=satisfied,
                detail=f"{count} holdings vs cardinality [{lo}, {hi}]",
                slack=slack,
            )
        )

    # TARGET_VOLATILITY — portfolio vol must stay under the target (ceiling); skipped if unknown.
    if constraints.target_volatility is not None and allocation.portfolio_volatility is not None:
        target = constraints.target_volatility
        actual = allocation.portfolio_volatility
        statuses.append(
            ConstraintStatus(
                ConstraintKind.TARGET_VOLATILITY,
                satisfied=actual <= target + WEIGHT_SUM_EPSILON,
                detail=f"portfolio volatility {actual} vs target {target}",
                slack=_normalized_slack(actual, target, ceiling=True),
            )
        )

    # TARGET_RETURN — portfolio return must meet the target (floor); skipped if unknown.
    if constraints.target_return is not None and allocation.portfolio_return is not None:
        target = constraints.target_return
        actual = allocation.portfolio_return
        statuses.append(
            ConstraintStatus(
                ConstraintKind.TARGET_RETURN,
                satisfied=actual >= target - WEIGHT_SUM_EPSILON,
                detail=f"portfolio return {actual} vs target {target}",
                slack=_normalized_slack(actual, target, ceiling=False),
            )
        )

    # TURNOVER — one-way turnover Σ|Δw|/2 vs limit; skipped without a prior allocation.
    if constraints.max_turnover is not None and allocation.prior_weights is not None:
        prior = allocation.prior_weights
        two = Decimal(2)
        gross = sum(
            (
                abs(weights.get(k, _ZERO) - prior.get(k, _ZERO))
                for k in weights.keys() | prior.keys()
            ),
            _ZERO,
        )
        turnover = gross / two
        limit = constraints.max_turnover
        statuses.append(
            ConstraintStatus(
                ConstraintKind.TURNOVER,
                satisfied=turnover <= limit + WEIGHT_SUM_EPSILON,
                detail=f"one-way turnover {turnover} vs max_turnover {limit}",
                slack=_normalized_slack(turnover, limit, ceiling=True),
            )
        )

    # FULL_INVESTMENT — always on: weights must sum to 1.0 within epsilon.
    total = sum(weights.values(), _ZERO)
    deviation = abs(total - _ONE)
    statuses.append(
        ConstraintStatus(
            ConstraintKind.FULL_INVESTMENT,
            satisfied=deviation <= WEIGHT_SUM_EPSILON,
            detail=f"weights sum to {total}, must equal 1.0 (+/-{WEIGHT_SUM_EPSILON})",
            slack=WEIGHT_SUM_EPSILON - deviation,
        )
    )

    ordered = tuple(statuses)
    binding = _pick_binding(ordered)
    return ConstraintReport(feasible=binding is None, statuses=ordered, binding=binding)


def feasibility(
    constraints: Constraints,
    universe_size: int,
    sector_universe: Mapping[str, int],
) -> ConstraintReport:
    """Structural pre-check: is the constraint set satisfiable at all, before any optimizer runs?

    Catches contradictions that need no expected-returns/covariance: too-large ``cardinality_min``,
    a ``max_weight`` too small to reach full investment, a ``min_weight``/``cardinality_min`` that
    forces over-allocation, and fully-capped sectors whose caps cannot sum to 1. ``target_return``
    reachability (needs mu) is deliberately out of scope — the optimizer validates it (QV-054).
    """
    statuses: list[ConstraintStatus] = []

    # CARDINALITY — can't hold more distinct names than exist.
    if constraints.cardinality_min is not None:
        lo = constraints.cardinality_min
        statuses.append(
            ConstraintStatus(
                ConstraintKind.CARDINALITY,
                satisfied=lo <= universe_size,
                detail=f"cardinality_min {lo} vs universe size {universe_size}",
                slack=_normalized_slack(Decimal(lo), Decimal(universe_size), ceiling=True),
            )
        )

    # MAX_WEIGHT — max_weight * (names you may hold) must be able to reach 1.0.
    if constraints.max_weight is not None:
        n_max = (
            universe_size
            if constraints.cardinality_max is None
            else min(constraints.cardinality_max, universe_size)
        )
        reachable = constraints.max_weight * Decimal(n_max)
        statuses.append(
            ConstraintStatus(
                ConstraintKind.MAX_WEIGHT,
                satisfied=reachable >= _ONE - WEIGHT_SUM_EPSILON,
                detail=(
                    f"max_weight {constraints.max_weight} over {n_max} names "
                    f"reaches {reachable} (need 1.0)"
                ),
                slack=_normalized_slack(_ONE, reachable, ceiling=True),
            )
        )

    # MIN_WEIGHT — being forced to hold cardinality_min names at the floor can't exceed 1.0.
    if constraints.min_weight > _ZERO and constraints.cardinality_min is not None:
        forced = constraints.min_weight * Decimal(constraints.cardinality_min)
        statuses.append(
            ConstraintStatus(
                ConstraintKind.MIN_WEIGHT,
                satisfied=forced <= _ONE + WEIGHT_SUM_EPSILON,
                detail=(
                    f"min_weight {constraints.min_weight} over "
                    f"{constraints.cardinality_min} names forces {forced} (max 1.0)"
                ),
                slack=_normalized_slack(forced, _ONE, ceiling=True),
            )
        )

    # SECTOR_CAP — if every available sector is capped, the caps must be able to sum to 1.0.
    if constraints.sector_caps and sector_universe:
        all_capped = all(s in constraints.sector_caps for s in sector_universe)
        if all_capped:
            reachable = sum((constraints.sector_caps[s] for s in sector_universe), _ZERO)
            statuses.append(
                ConstraintStatus(
                    ConstraintKind.SECTOR_CAP,
                    satisfied=reachable >= _ONE - WEIGHT_SUM_EPSILON,
                    detail=f"sector caps sum to {reachable} across all sectors (need 1.0)",
                    slack=_normalized_slack(_ONE, reachable, ceiling=True),
                )
            )

    ordered = tuple(statuses)
    binding = _pick_binding(ordered)
    return ConstraintReport(feasible=binding is None, statuses=ordered, binding=binding)


def raise_if_infeasible(report: ConstraintReport) -> None:
    """Raise :class:`InfeasibleConstraints` (carrying the binding status) if infeasible."""
    if not report.feasible and report.binding is not None:
        raise InfeasibleConstraints(report.binding)


__all__ = [
    "Allocation",
    "ConstraintKind",
    "ConstraintReport",
    "ConstraintStatus",
    "Constraints",
    "InfeasibleConstraints",
    "check",
    "feasibility",
    "raise_if_infeasible",
]

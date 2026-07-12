"""portfolio — services (QV-051).

The `portfolios` plan-limit guard, reused by the CRUD API (QV-052). Kept **pure** in `(count,
limit)` so it's unit-testable without a DB; the route supplies `count_portfolios(session)` and
`EntitlementService.limit(tenant_id, PORTFOLIO_LIMIT_KEY)` — exactly the alerts-route pattern.
`portfolio` may import `identity` (higher → lower in the bounded-context DAG).
"""

from __future__ import annotations

from decimal import Decimal

from quantvista.identity.models import EntitlementExceeded

# The seeded entitlement key for the portfolio count quota (Free 1 / Pro 5 / Quant unlimited).
PORTFOLIO_LIMIT_KEY = "portfolios"

# Tolerance for the target-weight sum check: Decimal weights rounded to numeric(9,6) can overshoot
# 1.0 by rounding dust (e.g. 0.333334 × 3 = 1.000002). Reject only a *material* over-allocation.
WEIGHT_SUM_EPSILON = Decimal("0.0001")


class WeightValidationError(Exception):
    """Position target-weights over-allocate (sum > 1) → ``validation_error`` (422)."""

    def __init__(self, total: Decimal) -> None:
        self.total = total
        super().__init__(f"position target weights sum to {total}, exceeding 1.0")


def enforce_portfolio_limit(*, current_count: int, limit: int | None) -> None:
    """Raise `EntitlementExceeded('portfolios')` when creating one more would exceed the plan quota.

    `limit is None` means unlimited (Quant tier, or the key is unset). No-op when under the quota.
    """
    if limit is not None and current_count >= limit:
        raise EntitlementExceeded(PORTFOLIO_LIMIT_KEY)


def validate_position_weights(target_weights: list[Decimal | None]) -> None:
    """Raise `WeightValidationError` when a portfolio's target weights over-allocate (sum > 1).

    Pure guard (list in → raise/none), so it unit-tests without a DB — mirrors
    `enforce_portfolio_limit`. `None` entries (positions without a target weight) are ignored.
    Per-field ``[0, 1]`` bounds are enforced at the DTO edge (`schemas.portfolios`).
    """
    total = sum((w for w in target_weights if w is not None), Decimal(0))
    if total > Decimal(1) + WEIGHT_SUM_EPSILON:
        raise WeightValidationError(total)

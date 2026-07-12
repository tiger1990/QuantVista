"""portfolio — services (QV-051).

The `portfolios` plan-limit guard, reused by the CRUD API (QV-052). Kept **pure** in `(count,
limit)` so it's unit-testable without a DB; the route supplies `count_portfolios(session)` and
`EntitlementService.limit(tenant_id, PORTFOLIO_LIMIT_KEY)` — exactly the alerts-route pattern.
`portfolio` may import `identity` (higher → lower in the bounded-context DAG).
"""

from __future__ import annotations

from quantvista.identity.models import EntitlementExceeded

# The seeded entitlement key for the portfolio count quota (Free 1 / Pro 5 / Quant unlimited).
PORTFOLIO_LIMIT_KEY = "portfolios"


def enforce_portfolio_limit(*, current_count: int, limit: int | None) -> None:
    """Raise `EntitlementExceeded('portfolios')` when creating one more would exceed the plan quota.

    `limit is None` means unlimited (Quant tier, or the key is unset). No-op when under the quota.
    """
    if limit is not None and current_count >= limit:
        raise EntitlementExceeded(PORTFOLIO_LIMIT_KEY)

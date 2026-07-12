"""Unit tests for the portfolio plan-limit guard (portfolio.services, QV-051) — pure, no DB.

The guard is pure given ``(current_count, limit)`` so it's trivially testable; the QV-052 CRUD
route supplies ``count_portfolios(session)`` and ``EntitlementService.limit(tenant_id, key)``
(mirrors the alerts route guard).
"""

from __future__ import annotations

import pytest

from quantvista.identity.models import EntitlementExceeded
from quantvista.portfolio.services import PORTFOLIO_LIMIT_KEY, enforce_portfolio_limit


def test_unlimited_plan_never_raises() -> None:
    enforce_portfolio_limit(current_count=999, limit=None)  # None = unlimited (Quant/unset)


def test_under_limit_is_allowed() -> None:
    enforce_portfolio_limit(current_count=0, limit=1)  # Free: 0 existing, creating the 1st is fine


@pytest.mark.parametrize("count", [1, 2, 5])
def test_at_or_over_limit_raises(count: int) -> None:
    with pytest.raises(EntitlementExceeded) as exc:
        enforce_portfolio_limit(current_count=count, limit=1)
    assert exc.value.feature == PORTFOLIO_LIMIT_KEY

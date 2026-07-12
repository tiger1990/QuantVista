"""Unit tests for the portfolio plan-limit guard (portfolio.services, QV-051) — pure, no DB.

The guard is pure given ``(current_count, limit)`` so it's trivially testable; the QV-052 CRUD
route supplies ``count_portfolios(session)`` and ``EntitlementService.limit(tenant_id, key)``
(mirrors the alerts route guard).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quantvista.identity.models import EntitlementExceeded
from quantvista.portfolio.services import (
    PORTFOLIO_LIMIT_KEY,
    WeightValidationError,
    enforce_portfolio_limit,
    validate_position_weights,
)


def test_unlimited_plan_never_raises() -> None:
    enforce_portfolio_limit(current_count=999, limit=None)  # None = unlimited (Quant/unset)


def test_under_limit_is_allowed() -> None:
    enforce_portfolio_limit(current_count=0, limit=1)  # Free: 0 existing, creating the 1st is fine


@pytest.mark.parametrize("count", [1, 2, 5])
def test_at_or_over_limit_raises(count: int) -> None:
    with pytest.raises(EntitlementExceeded) as exc:
        enforce_portfolio_limit(current_count=count, limit=1)
    assert exc.value.feature == PORTFOLIO_LIMIT_KEY


# --- validate_position_weights (pure cross-position sum guard) ---


def test_empty_weights_ok() -> None:
    validate_position_weights([])  # no positions → nothing to sum


def test_sum_under_one_ok() -> None:
    validate_position_weights([Decimal("0.3"), Decimal("0.2"), Decimal("0.4")])  # 0.9


def test_sum_exactly_one_ok() -> None:
    validate_position_weights([Decimal("0.5"), Decimal("0.5")])  # 1.0 is allowed


def test_sum_within_epsilon_ok() -> None:
    # 0.333333 * 3 = 0.999999 (≤ 1); and a hair over 1 within epsilon is tolerated
    validate_position_weights([Decimal("0.333334"), Decimal("0.333334"), Decimal("0.333334")])


def test_sum_over_one_raises() -> None:
    with pytest.raises(WeightValidationError):
        validate_position_weights([Decimal("0.6"), Decimal("0.6")])  # 1.2 > 1


def test_none_weights_are_ignored() -> None:
    # positions without a target_weight don't contribute to the sum
    validate_position_weights([Decimal("0.5"), None, Decimal("0.4")])  # 0.9

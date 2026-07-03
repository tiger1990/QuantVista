"""Unit tests for the corporate-action adjustment math (market_data.adjustments)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from quantvista.market_data.adjustments import split_adjustment_steps


def test_no_splits_returns_no_steps() -> None:
    assert split_adjustment_steps([]) == []


def test_single_2_for_1_split_halves_prior_prices() -> None:
    steps = split_adjustment_steps([(date(2024, 6, 1), Decimal(2))])
    assert steps == [(date(2024, 6, 1), Decimal("0.5"))]


def test_multiple_splits_are_cumulative_and_desc_ordered() -> None:
    # A 3:1 (2023) then a 2:1 (2024). Returned newest-first; factors compound.
    steps = split_adjustment_steps([(date(2023, 1, 1), Decimal(3)), (date(2024, 6, 1), Decimal(2))])
    assert steps[0] == (date(2024, 6, 1), Decimal("0.5"))  # after the 2:1
    assert steps[1][0] == date(2023, 1, 1)
    assert steps[1][1] == Decimal("0.5") / Decimal(3)  # cumulative 1/6


def test_unsorted_input_is_handled() -> None:
    # Input order should not matter — sorted internally (newest ex_date first).
    steps = split_adjustment_steps([(date(2024, 6, 1), Decimal(2)), (date(2023, 1, 1), Decimal(3))])
    assert [d for d, _ in steps] == [date(2024, 6, 1), date(2023, 1, 1)]


def test_non_positive_ratio_is_skipped() -> None:
    assert split_adjustment_steps([(date(2024, 6, 1), Decimal(0))]) == []

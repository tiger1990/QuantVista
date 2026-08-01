"""Month arithmetic + naming for partition maintenance (QV-104) — no DB."""

from __future__ import annotations

from datetime import date

from quantvista.core.partitions import (
    DEFAULT_MONTHS_AHEAD,
    partition_name,
    upcoming_months,
)


def test_upcoming_months_starts_at_the_current_month() -> None:
    months = upcoming_months(date(2026, 8, 14), months_ahead=2)
    assert months == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]


def test_upcoming_months_rolls_over_the_year() -> None:
    """The December→January boundary is where naive month arithmetic breaks."""
    assert upcoming_months(date(2026, 12, 31), months_ahead=2) == [
        date(2026, 12, 1),
        date(2027, 1, 1),
        date(2027, 2, 1),
    ]


def test_default_lookahead_covers_more_than_next_month() -> None:
    """The bug was having only current+next; a single missed run must not strand the data."""
    assert DEFAULT_MONTHS_AHEAD >= 2
    assert len(upcoming_months(date(2026, 8, 1))) == DEFAULT_MONTHS_AHEAD + 1


def test_partition_name_matches_the_sql_helper() -> None:
    # `create_month_partition` formats as '%s_%s' with to_char(month, 'YYYY_MM')
    assert partition_name("daily_prices", date(2026, 8, 1)) == "daily_prices_2026_08"
    assert partition_name("scores", date(2026, 12, 1)) == "scores_2026_12"

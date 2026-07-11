"""Unit tests for the pure decayed-sentiment aggregation (QV-046)."""

from __future__ import annotations

from datetime import date

from quantvista.analytics.sentiment import decayed_sentiment


def test_empty_is_none() -> None:
    assert decayed_sentiment([], date(2026, 7, 11)) is None


def test_single_row_is_its_value() -> None:
    assert decayed_sentiment([(date(2026, 7, 11), 42.0)], date(2026, 7, 11)) == 42.0


def test_recent_news_outweighs_old() -> None:
    as_of = date(2026, 7, 11)
    # fresh +100 vs 30-day-old -100 → recent dominates → positive
    agg = decayed_sentiment([(date(2026, 7, 11), 100.0), (date(2026, 6, 11), -100.0)], as_of)
    assert agg is not None and agg > 0


def test_equal_age_is_plain_mean() -> None:
    as_of = date(2026, 7, 11)
    agg = decayed_sentiment([(as_of, 60.0), (as_of, -20.0)], as_of)
    assert agg == 20.0  # (60 + -20) / 2, weights equal


def test_half_life_halves_weight() -> None:
    as_of = date(2026, 7, 11)
    # one fresh (+40, w=1) and one exactly one half-life old (+40 at 7d, w=0.5) → still +40
    agg = decayed_sentiment([(as_of, 40.0), (date(2026, 7, 4), 40.0)], as_of, half_life_days=7.0)
    assert agg == 40.0


def test_future_published_clamped_not_amplified() -> None:
    # a published date after as_of (shouldn't happen post-PIT-filter) clamps age to 0, weight 1
    as_of = date(2026, 7, 11)
    agg = decayed_sentiment([(date(2026, 7, 20), 10.0)], as_of)
    assert agg == 10.0

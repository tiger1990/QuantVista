"""Decayed per-stock sentiment aggregation (QV-046) — pure, PIT-agnostic.

Turns a stock's PIT-visible per-article signals (QV-045 ``impact_score`` = news tone + event impact)
into one recency-weighted number for the ``SentimentFactor``. Older news weighs exponentially less
(a half-life), so a stale headline can't dominate today's score. The caller supplies only rows that
are already point-in-time-safe (published ≤ as_of, known by as_of); this module just weights them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

# News sentiment relevance fades over ~a week: a signal this many days old carries half the weight.
SENTIMENT_HALF_LIFE_DAYS = 7.0


def decayed_sentiment(
    rows: Sequence[tuple[date, float]],
    as_of: date,
    half_life_days: float = SENTIMENT_HALF_LIFE_DAYS,
) -> float | None:
    """Decay-weighted mean of ``(published_at, signal)`` rows; ``None`` when there are none.

    ``weight = 0.5 ** (age_days / half_life)``, ``age_days = max(0, as_of − published)`` (a
    future-dated row clamps to full weight rather than amplifying).
    """
    numerator = 0.0
    denominator = 0.0
    for published, signal in rows:
        age_days = max(0, (as_of - published).days)
        weight = 0.5 ** (age_days / half_life_days)
        numerator += weight * signal
        denominator += weight
    return numerator / denominator if denominator else None

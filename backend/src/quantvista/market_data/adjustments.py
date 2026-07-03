"""Corporate-action price adjustment (QV-017).

Computes the cumulative back-adjustment factors that turn raw ``close`` into a continuous
``adj_close`` so splits/bonuses don't fake momentum (``03`` §5). A split/bonus with ratio ``R``
on ``ex_date`` scales post-``ex_date`` prices down by ``R``; to keep history continuous, every
price with ``date < ex_date`` is multiplied by ``1/R`` (cumulative across later actions). The
price **on** the ex-date is already post-split → unadjusted. Dividends are NOT applied here.

Pure and ``Decimal``-exact — the repository applies the returned steps to ``daily_prices``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def split_adjustment_steps(
    splits: list[tuple[date, Decimal]],
) -> list[tuple[date, Decimal]]:
    """Return ``(ex_date, factor)`` steps for split/bonus ``(ex_date, ratio)`` inputs.

    ``factor`` is the cumulative multiplier applied to every price with ``date < ex_date``.
    Output is ordered by ``ex_date`` descending, so applying the steps in order as prefix
    updates (``date < ex_date``) yields the correct cumulative factor for every date.
    """
    steps: list[tuple[date, Decimal]] = []
    factor = Decimal(1)
    for ex_date, ratio in sorted(splits, key=lambda s: s[0], reverse=True):
        if ratio <= 0:  # defensive — non-positive ratios are meaningless, skip
            continue
        factor = factor / ratio
        steps.append((ex_date, factor))
    return steps

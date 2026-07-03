"""NSE trading-calendar helper (QV-016) over ``exchange_calendars``.

Wraps the maintained ``XBOM`` calendar — India's NSE & BSE share the same trading holidays,
so ``XBOM`` is the authoritative session calendar for our NSE universe. Drives which session
the daily ingest targets (Yahoo is T-1, so we take the last *completed* session strictly
before "now") and enumerates sessions across a backfill window. ``core``-free leaf.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import exchange_calendars as xcals

# India (NSE/BSE) trading calendar. exchange_calendars has no 'XNSE'; NSE and BSE observe the
# same holidays, so XBOM is the correct India session calendar.
_INDIA_CALENDAR = "XBOM"
# Lookback long enough to always span the longest NSE holiday cluster (Diwali etc.).
_MAX_HOLIDAY_GAP_DAYS = 12


@lru_cache(maxsize=1)
def _calendar() -> Any:
    return xcals.get_calendar(_INDIA_CALENDAR)


def is_session(on: date) -> bool:
    """True if ``on`` is an NSE trading session (not a weekend/holiday)."""
    return bool(_calendar().is_session(on.isoformat()))


def last_completed_session(as_of: date) -> date:
    """The most recent trading session strictly before ``as_of`` (T-1 safe for Yahoo's lag)."""
    sessions = sessions_in_range(
        as_of - timedelta(days=_MAX_HOLIDAY_GAP_DAYS), as_of - timedelta(days=1)
    )
    if not sessions:  # pragma: no cover - only if >12 consecutive non-session days
        raise ValueError(
            f"no NSE trading session found in the {_MAX_HOLIDAY_GAP_DAYS} days before {as_of}"
        )
    return sessions[-1]


def sessions_in_range(start: date, end: date) -> list[date]:
    """All trading sessions in ``[start, end]`` (inclusive), ascending."""
    if end < start:
        return []
    import pandas as pd

    sessions = _calendar().sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
    return [s.date() for s in sessions]

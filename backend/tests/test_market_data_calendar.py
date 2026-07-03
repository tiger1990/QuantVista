"""Unit tests for the NSE trading-calendar helper (market_data.trading_calendar)."""

from __future__ import annotations

from datetime import date

from quantvista.market_data import trading_calendar as tc
from quantvista.market_data.adapters.yfinance_dev import yahoo_symbol


def test_republic_day_is_not_a_session() -> None:
    # 2026-01-26 (Republic Day) is an NSE holiday
    assert tc.is_session(date(2026, 1, 26)) is False


def test_regular_weekday_is_a_session() -> None:
    # 2026-01-27 (Tue) is a normal trading day
    assert tc.is_session(date(2026, 1, 27)) is True


def test_weekend_is_not_a_session() -> None:
    assert tc.is_session(date(2026, 1, 24)) is False  # Saturday


def test_last_completed_session_skips_holiday_and_weekend() -> None:
    # As of Tue 2026-01-27: Mon 26 = Republic Day, 24/25 = weekend → last session = Fri 23
    assert tc.last_completed_session(date(2026, 1, 27)) == date(2026, 1, 23)


def test_sessions_in_range_excludes_holidays() -> None:
    sessions = tc.sessions_in_range(date(2026, 1, 23), date(2026, 1, 28))
    assert date(2026, 1, 26) not in sessions  # holiday excluded
    assert date(2026, 1, 24) not in sessions  # weekend excluded
    assert date(2026, 1, 23) in sessions and date(2026, 1, 27) in sessions


def test_yahoo_symbol_maps_market_suffix() -> None:
    assert yahoo_symbol("RELIANCE", "NSE") == "RELIANCE.NS"
    assert yahoo_symbol("RELIANCE", "BSE") == "RELIANCE.BO"
    assert yahoo_symbol("RELIANCE", "UNKNOWN") == "RELIANCE"  # no suffix for unknown market

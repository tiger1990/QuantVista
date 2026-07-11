"""Unit tests for YFinanceDevProvider.get_fundamentals (QV-095) — network-free.

A fake ticker returns canned statement DataFrames (yfinance shape: index = line item, columns =
period-end timestamps), so the statement→ratio mapping + dated snapshots are pinned without Yahoo.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from quantvista.market_data.adapters.yfinance_dev import YFinanceDevProvider

D = Decimal
P0, P1 = pd.Timestamp("2026-03-31"), pd.Timestamp("2025-03-31")

_INCOME = pd.DataFrame(
    {
        P0: {
            "Total Revenue": 1000,
            "Net Income": 120,
            "EBIT": 200,
            "EBITDA": 250,
            "Operating Income": 180,
            "Pretax Income": 160,
            "Tax Provision": 40,
        },
        P1: {
            "Total Revenue": 800,
            "Net Income": 90,
            "EBIT": 150,
            "EBITDA": 190,
            "Operating Income": 140,
            "Pretax Income": 120,
            "Tax Provision": 30,
        },
    }
)
_BALANCE = pd.DataFrame(
    {
        P0: {
            "Total Assets": 2000,
            "Current Assets": 600,
            "Current Liabilities": 400,
            "Inventory": 150,
            "Total Debt": 500,
            "Cash And Cash Equivalents": 100,
            "Stockholders Equity": 800,
            "Ordinary Shares Number": 100,
        },
        P1: {
            "Total Assets": 1800,
            "Current Assets": 550,
            "Current Liabilities": 380,
            "Inventory": 140,
            "Total Debt": 480,
            "Cash And Cash Equivalents": 90,
            "Stockholders Equity": 700,
            "Ordinary Shares Number": 100,
        },
    }
)
_CASHFLOW = pd.DataFrame(
    {
        P0: {"Operating Cash Flow": 160, "Capital Expenditure": -60},
        P1: {"Operating Cash Flow": 128, "Capital Expenditure": -48},
    }
)
_INFO = {"regularMarketPrice": 240, "sharesOutstanding": 100, "forwardEps": 1.5}


class _FakeTicker:
    income_stmt = _INCOME
    balance_sheet = _BALANCE
    cashflow = _CASHFLOW
    info = _INFO


def _provider(ticker: Any) -> YFinanceDevProvider:
    return YFinanceDevProvider(ticker_factory=lambda _s: ticker)


def test_returns_a_dated_snapshot_per_period() -> None:
    snaps = _provider(_FakeTicker()).get_fundamentals("RELIANCE")
    assert [s.period_end for s in snaps] == [date(2026, 3, 31), date(2025, 3, 31)]
    assert all(s.statement_type == "annual" for s in snaps)


def test_latest_period_has_intrinsic_and_valuation_ratios() -> None:
    latest = _provider(_FakeTicker()).get_fundamentals("RELIANCE")[0]
    assert latest.roe == D(120) / D(800)
    assert latest.roce == D(200) / (D(2000) - D(400))
    assert latest.debt_equity == D(500) / D(800)
    assert latest.eps == D(120) / D(100)
    assert latest.revenue_growth == (D(1000) - D(800)) / D(800)  # needs prior period
    assert latest.pe == D(240) / (D(120) / D(100))  # valuation from current price
    assert latest.pb == D(240) / (D(800) / D(100))


def test_older_period_has_no_valuation() -> None:
    older = _provider(_FakeTicker()).get_fundamentals("RELIANCE")[1]
    assert older.roe == D(90) / D(700)  # intrinsic computed
    assert older.pe is None and older.pb is None  # valuation only on the latest period


def test_empty_statements_return_nothing() -> None:
    class _Empty:
        income_stmt = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()
        info: dict[str, Any] = {}

    assert _provider(_Empty()).get_fundamentals("X") == []

"""Unit tests for the Polars technical-indicator math (market_data.indicators, QV-025).

Crafted series with known SMA/return/vol/beta so the vectorized math is pinned; short series prove
insufficient-history → NULL. Pure (no DB).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import polars as pl

from quantvista.market_data.indicators import compute_indicators_for_date

_D0 = date(2024, 1, 1)


def _series(stock: str, n: int, start: float = 100.0, step: float = 0.0) -> pl.DataFrame:
    dates = [_D0 + timedelta(days=i) for i in range(n)]
    prices = [start + step * i for i in range(n)]
    return pl.DataFrame(
        {
            "stock_id": [stock] * n,
            "date": dates,
            "adj_close": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
        }
    )


def _row(df: pl.DataFrame, stock: str) -> dict[str, Any]:
    return df.filter(pl.col("stock_id") == stock).to_dicts()[0]


def test_sma_and_returns_on_a_ramp() -> None:
    n = 260
    df = _series("AAA", n, start=100.0, step=1.0)  # 100,101,...,359
    target = _D0 + timedelta(days=n - 1)
    out = compute_indicators_for_date(df, target)
    r = _row(out, "AAA")
    last = 100.0 + (n - 1)  # 359
    assert abs(float(r["sma_50"]) - (last - 24.5)) < 1e-6  # mean of last 50 of a +1 ramp
    assert abs(float(r["ret_3m"]) - (last / (last - 63) - 1.0)) < 1e-6  # 63-session simple return


def test_constant_series_has_zero_vol_and_flat_bollinger() -> None:
    df = _series("BBB", 260, start=100.0, step=0.0)
    out = compute_indicators_for_date(df, _D0 + timedelta(days=259))
    r = _row(out, "BBB")
    assert abs(float(r["vol_30d"])) < 1e-9
    assert abs(float(r["bollinger_upper"]) - 100.0) < 1e-6
    assert abs(float(r["bollinger_lower"]) - 100.0) < 1e-6
    assert abs(float(r["ret_12m"])) < 1e-9


def test_rsi_is_100_for_a_strictly_rising_series() -> None:
    df = _series("CCC", 60, start=100.0, step=1.0)
    out = compute_indicators_for_date(df, _D0 + timedelta(days=59))
    r = _row(out, "CCC")
    assert abs(float(r["rsi_14"]) - 100.0) < 1e-6  # only gains → RSI 100


def test_single_stock_beta_is_one() -> None:
    # With one stock, the equal-weighted market return == the stock's return → beta = 1.
    df = _series("DDD", 260, start=100.0, step=0.7)
    out = compute_indicators_for_date(df, _D0 + timedelta(days=259))
    r = _row(out, "DDD")
    assert abs(float(r["beta_1y"]) - 1.0) < 1e-6


def test_insufficient_history_yields_nulls() -> None:
    df = _series("EEE", 30, start=100.0, step=1.0)  # only 30 sessions
    out = compute_indicators_for_date(df, _D0 + timedelta(days=29))
    r = _row(out, "EEE")
    assert r["sma_200"] is None  # needs 200
    assert r["ret_12m"] is None  # needs 252
    assert r["beta_1y"] is None  # needs 252
    assert r["ema_20"] is not None  # 20 available → computed

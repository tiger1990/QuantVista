"""Technical-indicator computation (QV-025) — Polars-vectorized, from adjusted close.

Pure: given a price history frame it returns one row of indicators per stock for a target date.
Momentum / return / vol / beta use ``adj_close`` (QV-017 split/bonus-adjusted) so corporate actions
don't fake signal; ATR-14 uses raw OHLC (short window). Indicators are statistical quantities →
computed in ``float64``; the repository rounds them into the ``numeric`` columns on store (the
"money stays Decimal" rule is about ledger values, not derived analytics). ``market_data`` DAG leaf.
"""

from __future__ import annotations

from datetime import date

import polars as pl

# Windows in trading sessions.
_SMA_50, _SMA_200, _EMA_20 = 50, 200, 20
_RSI, _ATR, _BOLL = 14, 14, 20
_MACD_FAST, _MACD_SLOW, _MACD_SIGNAL = 12, 26, 9
_RET_3M, _RET_6M, _RET_12M = 63, 126, 252
_VOL, _BETA = 30, 252
_ANNUALISE = 252**0.5

INDICATOR_COLUMNS = (
    "sma_50",
    "sma_200",
    "ema_20",
    "rsi_14",
    "macd",
    "macd_signal",
    "bollinger_upper",
    "bollinger_lower",
    "atr_14",
    "ret_3m",
    "ret_6m",
    "ret_12m",
    "vol_30d",
    "beta_1y",
)


def compute_indicators_for_date(prices: pl.DataFrame, target_date: date) -> pl.DataFrame:
    """One indicator row per stock for ``target_date`` from ``prices`` (stock_id, date, adj_close,
    high, low, close). Windows without enough history yield ``null``."""
    df = prices.sort(["stock_id", "date"]).with_columns(
        pl.col("adj_close").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
    )

    over = "stock_id"
    daily_ret = pl.col("adj_close").pct_change().over(over)
    # Equal-weighted market return per date (the beta benchmark proxy).
    df = df.with_columns(daily_ret.alias("_ret"))
    df = df.with_columns(pl.col("_ret").mean().over("date").alias("_mkt"))

    prev_close = pl.col("close").shift().over(over)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    delta = pl.col("adj_close").diff().over(over)
    gain = pl.when(delta > 0).then(delta).otherwise(0.0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
    avg_gain = gain.rolling_mean(_RSI).over(over)
    avg_loss = loss.rolling_mean(_RSI).over(over)
    rs = avg_gain / avg_loss
    # RSI: all-gains (avg_loss=0) → 100; no movement (both 0 → NaN) → null.
    rsi = pl.when(avg_loss == 0).then(100.0).otherwise(100.0 - 100.0 / (1.0 + rs))

    ema_fast = pl.col("adj_close").ewm_mean(span=_MACD_FAST, adjust=False).over(over)
    ema_slow = pl.col("adj_close").ewm_mean(span=_MACD_SLOW, adjust=False).over(over)
    macd = ema_fast - ema_slow
    sma_20 = pl.col("adj_close").rolling_mean(_BOLL).over(over)
    std_20 = pl.col("adj_close").rolling_std(_BOLL).over(over)

    xy = (pl.col("_ret") * pl.col("_mkt")).rolling_mean(_BETA).over(over)
    x = pl.col("_ret").rolling_mean(_BETA).over(over)
    y = pl.col("_mkt").rolling_mean(_BETA).over(over)
    yy = (pl.col("_mkt") * pl.col("_mkt")).rolling_mean(_BETA).over(over)
    cov = xy - x * y
    var = yy - y * y

    df = df.with_columns(
        pl.col("adj_close").rolling_mean(_SMA_50).over(over).alias("sma_50"),
        pl.col("adj_close").rolling_mean(_SMA_200).over(over).alias("sma_200"),
        pl.col("adj_close").ewm_mean(span=_EMA_20, adjust=False).over(over).alias("ema_20"),
        rsi.alias("rsi_14"),
        macd.alias("macd"),
        macd.ewm_mean(span=_MACD_SIGNAL, adjust=False).over(over).alias("macd_signal"),
        (sma_20 + 2.0 * std_20).alias("bollinger_upper"),
        (sma_20 - 2.0 * std_20).alias("bollinger_lower"),
        true_range.rolling_mean(_ATR).over(over).alias("atr_14"),
        (pl.col("adj_close") / pl.col("adj_close").shift(_RET_3M).over(over) - 1.0).alias("ret_3m"),
        (pl.col("adj_close") / pl.col("adj_close").shift(_RET_6M).over(over) - 1.0).alias("ret_6m"),
        (pl.col("adj_close") / pl.col("adj_close").shift(_RET_12M).over(over) - 1.0).alias(
            "ret_12m"
        ),
        (pl.col("_ret").rolling_std(_VOL).over(over) * _ANNUALISE).alias("vol_30d"),
        pl.when(var != 0).then(cov / var).otherwise(None).alias("beta_1y"),
    )

    return df.filter(pl.col("date") == target_date).select("stock_id", "date", *INDICATOR_COLUMNS)

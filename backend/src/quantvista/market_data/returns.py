"""market_data — PIT returns-matrix reader for the optimizer (QV-054).

Assembles a returns matrix from ``daily_prices.adj_close`` for a candidate universe, **point-in-time
bounded** (``date <= as_of`` — no look-ahead, project rule #4). ``daily_prices`` is a global table
(no ``tenant_id`` / no RLS — rule #1), so this read runs on any session. Names with insufficient
history are dropped and reported so the caller knows what was excluded. Returns a NumPy matrix; the
optimizer consumes it without touching SQL (keeps the optimizer DB-agnostic and unit-testable).

Simple returns ``rₜ = pₜ / pₜ₋₁ − 1`` over the dates common to all surviving names.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import text
from sqlalchemy.orm import Session

FloatMatrix = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ReturnsMatrix:
    """A ``(T returns, N assets)`` matrix with aligned column identity and row dates.

    ``stock_ids`` is the column order; ``dates`` are the T return dates; ``dropped`` lists names
    excluded for insufficient history (fewer than ``min_observations`` PIT prices).
    """

    values: FloatMatrix
    stock_ids: tuple[UUID, ...]
    dates: tuple[date, ...]
    dropped: tuple[UUID, ...]


_PRICES_SQL = (
    "SELECT stock_id, date, adj_close FROM daily_prices "
    "WHERE stock_id = ANY(:ids) AND date <= :as_of AND adj_close IS NOT NULL"
)


def returns_matrix_as_of(
    session: Session,
    stock_ids: Sequence[UUID],
    as_of: date,
    *,
    lookback_days: int | None = None,
    min_observations: int = 2,
) -> ReturnsMatrix:
    """Build a PIT simple-returns matrix for ``stock_ids`` as of ``as_of``.

    Only bars with ``date <= as_of`` are read (optionally also ``date >= as_of - lookback_days``).
    A name with fewer than ``min_observations`` prices is dropped and reported. Surviving names are
    aligned on their common dates; returns are computed over that aligned price panel.
    """
    requested = list(dict.fromkeys(stock_ids))  # de-dupe, preserve order
    params: dict[str, object] = {"ids": requested, "as_of": as_of}
    sql = _PRICES_SQL
    if lookback_days is not None:  # add the window floor only when set (avoids a NULL-typed param)
        sql += " AND date >= :start"
        params["start"] = as_of - timedelta(days=lookback_days)
    sql += " ORDER BY date"

    rows = session.execute(text(sql), params).all()

    # Per-stock date → adj_close (float).
    prices: dict[UUID, dict[date, float]] = {}
    for stock_id, bar_date, adj_close in rows:
        prices.setdefault(stock_id, {})[bar_date] = float(adj_close)

    eligible = [s for s in requested if len(prices.get(s, {})) >= min_observations]
    dropped = tuple(s for s in requested if s not in eligible)

    if not eligible:
        return ReturnsMatrix(
            values=np.empty((0, 0), dtype=np.float64), stock_ids=(), dates=(), dropped=dropped
        )

    common: set[date] = set(prices[eligible[0]])
    for s in eligible[1:]:
        common &= set(prices[s])
    aligned_dates = sorted(common)

    if len(aligned_dates) < 2:  # need ≥2 aligned prices for ≥1 return
        return ReturnsMatrix(
            values=np.empty((0, len(eligible)), dtype=np.float64),
            stock_ids=tuple(eligible),
            dates=(),
            dropped=dropped,
        )

    # Price panel (len(dates) × N), then simple returns over rows.
    panel = np.array([[prices[s][d] for s in eligible] for d in aligned_dates], dtype=np.float64)
    returns = panel[1:] / panel[:-1] - 1.0
    return ReturnsMatrix(
        values=returns,
        stock_ids=tuple(eligible),
        dates=tuple(aligned_dates[1:]),
        dropped=dropped,
    )


__all__ = ["ReturnsMatrix", "returns_matrix_as_of"]

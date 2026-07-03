"""market_data — data access for the reference/price tables (QV-016).

Global-table access: the universe read + the ``daily_prices`` upsert both run on the
**privileged** engine (these tables carry no ``tenant_id`` / no RLS). Money stays ``Decimal``.
The upsert is keyed ``(stock_id, date)`` so re-running a session never duplicates.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.market_data.adjustments import split_adjustment_steps
from quantvista.market_data.models import CorporateAction, PriceBar


@dataclass(frozen=True, slots=True)
class UniverseStock:
    """A member of the active ingest universe (canonical identity)."""

    stock_id: UUID
    symbol: str
    market: str


_ACTIVE_UNIVERSE_SQL = text(
    """
    SELECT s.id, s.symbol, m.code
    FROM index_constituents ic
    JOIN stocks s  ON s.id = ic.stock_id AND s.is_active
    JOIN markets m ON m.id = s.market_id
    WHERE ic.index_code = :index_code
      AND ic.effective_to IS NULL          -- open (current) membership
      AND m.code = :market_code
    ORDER BY s.symbol
    """
)

# adj_close is seeded with the RAW close (placeholder). The corporate-action-adjusted value
# is computed by QV-017 — we never trust the provider's adjusted close (03 §5).
_UPSERT_SQL = text(
    """
    INSERT INTO daily_prices
        (stock_id, date, open, high, low, close, adj_close, volume, source)
    VALUES
        (:stock_id, :date, :open, :high, :low, :close, :adj_close, :volume, :source)
    ON CONFLICT (stock_id, date) DO UPDATE SET
        open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
        close = EXCLUDED.close, adj_close = EXCLUDED.adj_close,
        volume = EXCLUDED.volume, source = EXCLUDED.source, ingested_at = now()
    """
)


def active_universe(session: Session, index_code: str, market_code: str) -> list[UniverseStock]:
    """Current members of ``index_code`` on ``market_code`` (open constituents, active stocks)."""
    rows = session.execute(
        _ACTIVE_UNIVERSE_SQL, {"index_code": index_code, "market_code": market_code}
    ).all()
    return [UniverseStock(stock_id=r[0], symbol=r[1], market=r[2]) for r in rows]


def upsert_daily_prices(session: Session, stock_id: UUID, bars: Sequence[PriceBar]) -> int:
    """Idempotently upsert OHLCV bars for ``stock_id``; returns the number of bars written."""
    if not bars:
        return 0
    params = [
        {
            "stock_id": stock_id,
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "adj_close": bar.close,  # raw-close placeholder until QV-017
            "volume": bar.volume,
            "source": bar.provenance.source,
        }
        for bar in bars
    ]
    session.execute(_UPSERT_SQL, params)
    return len(params)


# --- corporate actions + adjusted-close (QV-017) -----------------------------
_UPSERT_CA_SQL = text(
    """
    INSERT INTO corporate_actions
        (stock_id, ex_date, action_type, ratio_or_amount, details, source)
    VALUES
        (:stock_id, :ex_date, :action_type, :ratio, CAST(:details AS jsonb), :source)
    ON CONFLICT (stock_id, ex_date, action_type) DO UPDATE SET
        ratio_or_amount = EXCLUDED.ratio_or_amount, details = EXCLUDED.details,
        source = EXCLUDED.source, ingested_at = now()
    """
)

# Only split/bonus actions drive price adjustment (dividends are stored, not applied).
_SPLIT_ROWS_SQL = text(
    "SELECT ex_date, ratio_or_amount FROM corporate_actions "
    "WHERE stock_id = :s AND action_type IN ('split', 'bonus') AND ratio_or_amount > 0"
)
_RESET_ADJ_SQL = text("UPDATE daily_prices SET adj_close = close WHERE stock_id = :s")
_ADJ_PREFIX_SQL = text(
    "UPDATE daily_prices SET adj_close = close * :f WHERE stock_id = :s AND date < :e"
)
_PRICE_COUNT_SQL = text("SELECT count(*) FROM daily_prices WHERE stock_id = :s")


def upsert_corporate_actions(
    session: Session, stock_id: UUID, actions: Sequence[CorporateAction]
) -> int:
    """Idempotently upsert corporate actions keyed ``(stock_id, ex_date, action_type)``."""
    if not actions:
        return 0
    params = [
        {
            "stock_id": stock_id,
            "ex_date": a.ex_date,
            "action_type": a.action_type.value,
            "ratio": a.ratio_or_amount,
            "details": json.dumps(a.details),
            "source": a.provenance.source,
        }
        for a in actions
    ]
    session.execute(_UPSERT_CA_SQL, params)
    return len(params)


def recompute_adjusted_close(session: Session, stock_id: UUID) -> int:
    """Recompute ``daily_prices.adj_close`` from raw ``close`` + split/bonus actions.

    Deterministic + idempotent: resets ``adj_close = close``, then applies each cumulative
    factor to the prefix of dates before its ex-date. Returns the number of price rows touched.
    """
    splits: list[tuple[object, Decimal]] = [
        (r[0], r[1]) for r in session.execute(_SPLIT_ROWS_SQL, {"s": stock_id}).all()
    ]
    session.execute(_RESET_ADJ_SQL, {"s": stock_id})
    for ex_date, factor in split_adjustment_steps(splits):  # type: ignore[arg-type]
        session.execute(_ADJ_PREFIX_SQL, {"f": factor, "s": stock_id, "e": ex_date})
    return int(session.execute(_PRICE_COUNT_SQL, {"s": stock_id}).scalar_one())

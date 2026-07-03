"""market_data — data access for the reference/price tables (QV-016).

Global-table access: the universe read + the ``daily_prices`` upsert both run on the
**privileged** engine (these tables carry no ``tenant_id`` / no RLS). Money stays ``Decimal``.
The upsert is keyed ``(stock_id, date)`` so re-running a session never duplicates.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.market_data.models import PriceBar


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

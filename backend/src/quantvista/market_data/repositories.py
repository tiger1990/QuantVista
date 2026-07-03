"""market_data — data access for the reference/price tables (QV-016).

Global-table access: the universe read + the ``daily_prices`` upsert both run on the
**privileged** engine (these tables carry no ``tenant_id`` / no RLS). Money stays ``Decimal``.
The upsert is keyed ``(stock_id, date)`` so re-running a session never duplicates.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.market_data.adjustments import split_adjustment_steps
from quantvista.market_data.models import CorporateAction, PriceBar, UniverseEntry
from quantvista.market_data.quality import PriceQualityMetrics


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


_LATEST_PRICE_DATE_SQL = text("SELECT max(date) FROM daily_prices")


def latest_price_date(session: Session) -> date | None:
    """The newest ``daily_prices.date`` (freshness source for QV-020); ``None`` if empty."""
    latest: date | None = session.execute(_LATEST_PRICE_DATE_SQL).scalar_one()
    return latest


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


# --- data-quality metrics (QV-018) -------------------------------------------
# One set-based pass over daily_prices for the universe + window. adj_close is excluded from
# null/sanity (it is recomputed asynchronously by the corp-action job and may lag a fresh ingest).
_QUALITY_AGG_SQL = text(
    """
    SELECT
        count(DISTINCT stock_id)                                       AS stocks_with_data,
        count(*)                                                       AS observed_slots,
        coalesce(sum(
            (open IS NULL)::int + (high IS NULL)::int + (low IS NULL)::int
            + (close IS NULL)::int + (volume IS NULL)::int
        ), 0)                                                          AS ohlcv_null_cells,
        count(*) FILTER (
            WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
        )                                                              AS nonpositive_price_rows,
        count(*) FILTER (
            WHERE high < low OR high < open OR high < close OR low > open OR low > close
        )                                                              AS ohlc_bound_violation_rows
    FROM daily_prices
    WHERE stock_id = ANY(:ids) AND date BETWEEN :start AND :end
    """
)
_MISSING_SYMBOLS_SQL = text(
    """
    SELECT s.symbol
    FROM stocks s
    WHERE s.id = ANY(:ids)
      AND NOT EXISTS (
          SELECT 1 FROM daily_prices dp
          WHERE dp.stock_id = s.id AND dp.date BETWEEN :start AND :end
      )
    ORDER BY s.symbol
    LIMIT :cap
    """
)


def price_quality_metrics(
    session: Session,
    stock_ids: Sequence[UUID],
    start: date,
    end: date,
    *,
    expected_sessions: int,
    missing_sample_cap: int = 10,
) -> PriceQualityMetrics:
    """Gather the aggregate metrics the quality gates evaluate over ``[start, end]``."""
    ids = list(stock_ids)
    row = session.execute(_QUALITY_AGG_SQL, {"ids": ids, "start": start, "end": end}).one()
    missing = [
        r[0]
        for r in session.execute(
            _MISSING_SYMBOLS_SQL,
            {"ids": ids, "start": start, "end": end, "cap": missing_sample_cap},
        )
    ]
    observed_slots = int(row.observed_slots)
    return PriceQualityMetrics(
        expected_stocks=len(ids),
        stocks_with_data=int(row.stocks_with_data),
        ohlcv_null_cells=int(row.ohlcv_null_cells),
        ohlcv_total_cells=observed_slots * 5,
        nonpositive_price_rows=int(row.nonpositive_price_rows),
        ohlc_bound_violation_rows=int(row.ohlc_bound_violation_rows),
        expected_sessions=expected_sessions,
        observed_slots=observed_slots,
        missing_symbols_sample=missing,
    )


# --- universe sync: security master + PIT index membership (QV-019) -----------
# Master upsert never delists (the security catalogue is not the index). RETURNING (xmax = 0)
# distinguishes an insert (xmax 0) from an update.
_UPSERT_STOCK_SQL = text(
    """
    INSERT INTO stocks (market_id, symbol, company_name, isin, is_active)
    SELECT m.id, :symbol, :company_name, :isin, :is_active
    FROM markets m WHERE m.code = :market_code
    ON CONFLICT (market_id, symbol) DO UPDATE
        SET company_name = EXCLUDED.company_name,
            isin         = COALESCE(EXCLUDED.isin, stocks.isin),
            is_active    = EXCLUDED.is_active,
            updated_at   = now()
    RETURNING (xmax = 0) AS inserted
    """
)
_RESOLVE_STOCKS_SQL = text(
    """
    SELECT s.id, s.symbol
    FROM stocks s JOIN markets m ON m.id = s.market_id AND m.code = :market_code
    WHERE s.symbol = ANY(:symbols)
    """
)
_OPEN_MEMBERS_SQL = text(
    "SELECT stock_id, effective_from FROM index_constituents "
    "WHERE index_code = :index_code AND effective_to IS NULL"
)
_INSERT_MEMBER_SQL = text(
    "INSERT INTO index_constituents (index_code, stock_id, effective_from, effective_to, weight) "
    "VALUES (:index_code, :stock_id, :effective_from, NULL, :weight)"
)
_CLOSE_MEMBER_SQL = text(
    "UPDATE index_constituents SET effective_to = :effective_to "
    "WHERE index_code = :index_code AND stock_id = :stock_id AND effective_to IS NULL"
)
# Guard with IS DISTINCT FROM so an unchanged weight is a true no-op (no row write); it also
# handles the NULL <-> value transition (dev supplies NULL, a licensed feed supplies a number).
_UPDATE_WEIGHT_SQL = text(
    "UPDATE index_constituents SET weight = :weight "
    "WHERE index_code = :index_code AND stock_id = :stock_id AND effective_to IS NULL "
    "AND weight IS DISTINCT FROM :weight"
)


@dataclass(frozen=True, slots=True)
class ConstituentCounts:
    added: int
    closed: int
    unchanged: int
    unresolved: list[str]


def upsert_stocks(
    session: Session, market_code: str, entries: Sequence[UniverseEntry]
) -> tuple[int, int]:
    """Upsert the security master from provider entries. Returns ``(inserted, updated)``."""
    inserted = 0
    for e in entries:
        row = session.execute(
            _UPSERT_STOCK_SQL,
            {
                "market_code": market_code,
                "symbol": e.symbol,
                "company_name": e.name or e.symbol,  # company_name is NOT NULL
                "isin": e.isin,
                "is_active": e.is_active,
            },
        ).one()
        if row.inserted:
            inserted += 1
    return inserted, len(entries) - inserted


def reconcile_constituents(
    session: Session,
    index_code: str,
    market_code: str,
    members: Sequence[tuple[str, Decimal | None]],
    as_of: date,
) -> ConstituentCounts:
    """PIT-reconcile ``index_code`` membership to ``members``: open adds, close drops, set weights.

    Survivorship-free — drops set ``effective_to = as_of`` (never delete). A member whose symbol
    has no ``stocks`` row is returned as ``unresolved`` (the caller fails the run). ``as_of`` must
    be strictly after an open row's ``effective_from`` to close it (the schema CHECK).
    """
    symbols = [s for s, _ in members]
    id_by_symbol = {
        r.symbol: r.id
        for r in session.execute(
            _RESOLVE_STOCKS_SQL, {"market_code": market_code, "symbols": symbols}
        )
    }
    unresolved = [s for s in symbols if s not in id_by_symbol]
    if unresolved:
        # Abort untouched: an incomplete provider view would wrongly *close* the unresolved member
        # as a "drop". Fail loud, mutate nothing (the caller raises; master must run first).
        return ConstituentCounts(0, 0, 0, unresolved)
    weight_by_id = {id_by_symbol[s]: w for s, w in members if s in id_by_symbol}
    provider_ids = set(weight_by_id)

    open_from = {
        r.stock_id: r.effective_from
        for r in session.execute(_OPEN_MEMBERS_SQL, {"index_code": index_code})
    }
    open_ids = set(open_from)
    adds, drops, unchanged = (
        provider_ids - open_ids,
        open_ids - provider_ids,
        provider_ids & open_ids,
    )

    for sid in adds:
        session.execute(
            _INSERT_MEMBER_SQL,
            {
                "index_code": index_code,
                "stock_id": sid,
                "effective_from": as_of,
                "weight": weight_by_id[sid],
            },
        )
    closed = 0
    for sid in drops:
        if open_from[sid] < as_of:  # respect effective_to > effective_from
            session.execute(
                _CLOSE_MEMBER_SQL,
                {"index_code": index_code, "stock_id": sid, "effective_to": as_of},
            )
            closed += 1
    for sid in unchanged:
        session.execute(
            _UPDATE_WEIGHT_SQL,
            {"index_code": index_code, "stock_id": sid, "weight": weight_by_id[sid]},
        )
    return ConstituentCounts(len(adds), closed, len(unchanged), unresolved)

"""analytics — data access for scores + factor_values (QV-029).

Both tables are global (no RLS) and partitioned monthly → the **privileged** engine. Upserts are
keyed on the natural unique index so re-scoring a date never duplicates. Persists the ``StockScore``
decomposition: one ``factor_values`` row per stock×factor + one ``scores`` row per stock.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.analytics.scoring import FactorValue, StockScore

_UPSERT_SCORES_SQL = text(
    """
    INSERT INTO scores
        (stock_id, date, fundamental_score, momentum_score, quality_score, sentiment_score,
         risk_score, composite_score, coverage, weights_version, model_version)
    VALUES
        (:stock_id, :date, :fundamental, :momentum, :quality, :sentiment,
         :risk, :composite, :coverage, :weights_version, :model_version)
    ON CONFLICT (stock_id, date) DO UPDATE SET
        fundamental_score = EXCLUDED.fundamental_score,
        momentum_score = EXCLUDED.momentum_score,
        quality_score = EXCLUDED.quality_score,
        sentiment_score = EXCLUDED.sentiment_score,
        risk_score = EXCLUDED.risk_score,
        composite_score = EXCLUDED.composite_score,
        coverage = EXCLUDED.coverage,
        weights_version = EXCLUDED.weights_version,
        model_version = EXCLUDED.model_version,
        created_at = now()
    """
)

_UPSERT_FACTOR_VALUES_SQL = text(
    """
    INSERT INTO factor_values
        (stock_id, date, factor_key, raw_value, zscore, percentile_sector, percentile_universe)
    VALUES
        (:stock_id, :date, :factor_key, :raw_value, :zscore, :percentile_sector,
         :percentile_universe)
    ON CONFLICT (stock_id, date, factor_key) DO UPDATE SET
        raw_value = EXCLUDED.raw_value, zscore = EXCLUDED.zscore,
        percentile_sector = EXCLUDED.percentile_sector,
        percentile_universe = EXCLUDED.percentile_universe
    """
)


def upsert_scores(session: Session, scores: Sequence[StockScore]) -> int:
    """Upsert one ``scores`` row per stock (``ON CONFLICT (stock_id, date)``)."""
    if not scores:
        return 0
    params = [
        {
            "stock_id": s.stock_id,
            "date": s.date,
            "fundamental": s.fundamental,
            "momentum": s.momentum,
            "quality": s.quality,
            "sentiment": s.sentiment,
            "risk": s.risk,
            "composite": s.composite,
            "coverage": s.coverage,
            "weights_version": s.weights_version,
            "model_version": s.model_version,
        }
        for s in scores
    ]
    session.execute(_UPSERT_SCORES_SQL, params)
    return len(params)


def upsert_factor_values(
    session: Session, as_of: date, snapshot: Mapping[UUID, Sequence[FactorValue]]
) -> int:
    """Upsert the canonical factor snapshot (``ON CONFLICT (stock_id, date, factor_key)``)."""
    params = [
        {
            "stock_id": stock_id,
            "date": as_of,
            "factor_key": fv.factor_key,
            "raw_value": fv.raw_value,
            "zscore": fv.zscore,
            "percentile_sector": fv.percentile_sector,
            "percentile_universe": fv.percentile_universe,
        }
        for stock_id, fvs in snapshot.items()
        for fv in fvs
    ]
    if not params:
        return 0
    session.execute(_UPSERT_FACTOR_VALUES_SQL, params)
    return len(params)


_FACTOR_VALUES_FOR_SQL = text(
    """
    SELECT stock_id, factor_key, raw_value, zscore, percentile_sector, percentile_universe
    FROM factor_values WHERE stock_id = ANY(:ids) AND date = :date
    """
)


def factor_values_for(
    session: Session, stock_ids: Sequence[UUID], as_of: date
) -> dict[UUID, list[FactorValue]]:
    """Read the persisted factor snapshot for ``(universe, date)`` back into ``FactorValue``s.

    The canonical artifact ``compute_scores`` projects — read in one query so scores bind to a
    single committed ``(market, date, model_version)`` snapshot, not a partially-refreshed dataset.
    """
    rows = session.execute(_FACTOR_VALUES_FOR_SQL, {"ids": list(stock_ids), "date": as_of}).all()
    by_stock: dict[UUID, list[FactorValue]] = defaultdict(list)
    for r in rows:
        by_stock[r.stock_id].append(
            FactorValue(
                r.factor_key,
                float(r.raw_value),
                float(r.zscore),
                float(r.percentile_sector),
                float(r.percentile_universe),
            )
        )
    return dict(by_stock)


# --- rankings read (QV-031 caching) ------------------------------------------
_RANKINGS_SQL = text(
    """
    SELECT st.symbol, sc.composite_score, sc.coverage, sc.model_version, sc.weights_version,
        (SELECT p.close FROM daily_prices p
         WHERE p.stock_id = st.id ORDER BY p.date DESC LIMIT 1) AS close
    FROM scores sc
    JOIN stocks st ON st.id = sc.stock_id
    JOIN markets m ON m.id = st.market_id
    WHERE sc.date = :date AND m.code = :market
    ORDER BY sc.composite_score DESC NULLS LAST, st.symbol
    """
)


def rankings_for(session: Session, market: str, as_of: date) -> list[dict[str, object]]:
    """Ranked composite scores (desc) for ``market`` on ``as_of`` — the cacheable read (03 §8)."""
    rows = session.execute(_RANKINGS_SQL, {"date": as_of, "market": market}).mappings().all()
    return [
        {
            "symbol": r["symbol"],
            "composite_score": None
            if r["composite_score"] is None
            else float(r["composite_score"]),
            "coverage": None if r["coverage"] is None else float(r["coverage"]),
            "close": _f(r["close"]),
            "model_version": r["model_version"],
            "weights_version": r["weights_version"],
        }
        for r in rows
    ]


# --- stock read-models (QV-032 API) ------------------------------------------
def _f(x: Any) -> float | None:
    return None if x is None else float(x)  # Decimal → float, None passthrough


_LIST_STOCKS_SQL = text(
    """
    SELECT s.symbol, s.company_name, s.sector, s.market_cap_bucket, m.code AS market,
        (SELECT sc.composite_score FROM scores sc
         WHERE sc.stock_id = s.id ORDER BY sc.date DESC LIMIT 1) AS composite_score,
        (SELECT p.close FROM daily_prices p
         WHERE p.stock_id = s.id ORDER BY p.date DESC LIMIT 1) AS close
    FROM stocks s
    JOIN markets m ON m.id = s.market_id
    WHERE m.code = :market
      AND (CAST(:sector AS text) IS NULL OR s.sector = :sector)
      AND (CAST(:cap AS text) IS NULL OR s.market_cap_bucket = :cap)
      AND (CAST(:q AS text) IS NULL OR s.symbol ILIKE :q OR s.company_name ILIKE :q)
      AND (CAST(:after AS text) IS NULL OR s.symbol > :after)
    ORDER BY s.symbol
    LIMIT :limit
    """
)


def list_stocks(
    session: Session,
    *,
    market: str,
    sector: str | None,
    market_cap_bucket: str | None,
    limit: int,
    after_symbol: str | None,
    q: str | None = None,
) -> list[dict[str, object]]:
    """Universe browse: filtered, keyset-paginated (``symbol`` asc) stocks + latest composite.

    ``q`` is a free-text filter on symbol OR company name (case-insensitive substring).
    """
    term = q.strip() if q else None
    rows = (
        session.execute(
            _LIST_STOCKS_SQL,
            {
                "market": market,
                "sector": sector,
                "cap": market_cap_bucket,
                "q": f"%{term}%" if term else None,
                "after": after_symbol,
                "limit": limit,
            },
        )
        .mappings()
        .all()
    )
    return [
        {
            "symbol": r["symbol"],
            "company_name": r["company_name"],
            "sector": r["sector"],
            "market_cap_bucket": r["market_cap_bucket"],
            "market": r["market"],
            "composite_score": _f(r["composite_score"]),
            "close": _f(r["close"]),
        }
        for r in rows
    ]


_STOCK_DETAIL_SQL = text(
    """
    SELECT s.symbol, s.company_name, s.sector, s.industry, s.market_cap_bucket, m.code AS market,
        s.is_active, p.date AS price_date, p.close,
        sc.composite_score, sc.fundamental_score, sc.momentum_score, sc.quality_score,
        sc.sentiment_score, sc.risk_score, sc.coverage, sc.model_version, sc.weights_version,
        f.pe, f.pb, f.roe, f.roce, f.debt_equity
    FROM stocks s
    JOIN markets m ON m.id = s.market_id
    LEFT JOIN LATERAL (
        SELECT date, close FROM daily_prices WHERE stock_id = s.id ORDER BY date DESC LIMIT 1
    ) p ON true
    LEFT JOIN LATERAL (
        SELECT * FROM scores WHERE stock_id = s.id ORDER BY date DESC LIMIT 1
    ) sc ON true
    LEFT JOIN LATERAL (
        SELECT pe, pb, roe, roce, debt_equity FROM fundamentals
        WHERE stock_id = s.id AND knowledge_to IS NULL ORDER BY period_end DESC LIMIT 1
    ) f ON true
    WHERE s.symbol = :symbol
    """
)


def stock_detail(session: Session, symbol: str) -> dict[str, object] | None:
    """Master + latest snapshot (price/scores/fundamentals) for ``symbol``; ``None`` if unknown."""
    r = session.execute(_STOCK_DETAIL_SQL, {"symbol": symbol}).mappings().one_or_none()
    if r is None:
        return None
    return {
        "symbol": r["symbol"],
        "company_name": r["company_name"],
        "sector": r["sector"],
        "industry": r["industry"],
        "market_cap_bucket": r["market_cap_bucket"],
        "market": r["market"],
        "is_active": r["is_active"],
        "snapshot": {
            "price_date": r["price_date"].isoformat() if r["price_date"] else None,
            "close": _f(r["close"]),
            "composite_score": _f(r["composite_score"]),
            "fundamental_score": _f(r["fundamental_score"]),
            "momentum_score": _f(r["momentum_score"]),
            "quality_score": _f(r["quality_score"]),
            "sentiment_score": _f(r["sentiment_score"]),
            "risk_score": _f(r["risk_score"]),
            "coverage": _f(r["coverage"]),
            "model_version": r["model_version"],
            "weights_version": r["weights_version"],
            "pe": _f(r["pe"]),
            "pb": _f(r["pb"]),
            "roe": _f(r["roe"]),
            "roce": _f(r["roce"]),
            "debt_equity": _f(r["debt_equity"]),
        },
    }


# --- score reads (QV-033 API) ------------------------------------------------
_SCORE_OF_SQL = text(
    """
    SELECT sc.stock_id, sc.date, sc.fundamental_score, sc.momentum_score, sc.quality_score,
        sc.sentiment_score, sc.risk_score, sc.composite_score, sc.coverage,
        sc.weights_version, sc.model_version
    FROM scores sc
    JOIN stocks s ON s.id = sc.stock_id
    WHERE s.symbol = :symbol AND (CAST(:as_of AS date) IS NULL OR sc.date <= :as_of)
    ORDER BY sc.date DESC
    LIMIT 1
    """
)


def score_of(session: Session, symbol: str, as_of: date | None = None) -> dict[str, object] | None:
    """The latest score for ``symbol`` with ``date <= as_of`` (or latest); ``None`` if unscored."""
    r = session.execute(_SCORE_OF_SQL, {"symbol": symbol, "as_of": as_of}).mappings().one_or_none()
    if r is None:
        return None
    return {
        "stock_id": r["stock_id"],
        "date": r["date"],
        "fundamental": _f(r["fundamental_score"]),
        "momentum": _f(r["momentum_score"]),
        "quality": _f(r["quality_score"]),
        "sentiment": _f(r["sentiment_score"]),
        "risk": _f(r["risk_score"]),
        "composite": _f(r["composite_score"]),
        "coverage": _f(r["coverage"]),
        "weights_version": r["weights_version"],
        "model_version": r["model_version"],
    }


_LATEST_SCORE_DATE_SQL = text(
    """
    SELECT max(sc.date) FROM scores sc
    JOIN stocks s ON s.id = sc.stock_id
    JOIN markets m ON m.id = s.market_id
    WHERE m.code = :market AND (CAST(:ob AS date) IS NULL OR sc.date <= :ob)
    """
)


def latest_score_date(
    session: Session, *, market: str, on_or_before: date | None = None
) -> date | None:
    """The newest ``scores.date`` for ``market`` (≤ ``on_or_before`` if given); ``None`` if none."""
    newest: date | None = session.execute(
        _LATEST_SCORE_DATE_SQL, {"market": market, "ob": on_or_before}
    ).scalar_one()
    return newest


# --- screener (QV-038) -------------------------------------------------------
_SCREEN_CTE = """
    WITH screened AS (
        SELECT s.symbol, s.company_name, s.sector, s.market_cap_bucket, m.code AS market,
            sc.composite_score, sc.fundamental_score, sc.momentum_score, sc.quality_score,
            sc.sentiment_score, sc.risk_score, sc.coverage,
            f.pe, f.pb, f.roe, f.roce, f.debt_equity
        FROM stocks s
        JOIN markets m ON m.id = s.market_id
        LEFT JOIN LATERAL (
            SELECT * FROM scores WHERE stock_id = s.id ORDER BY date DESC LIMIT 1
        ) sc ON true
        LEFT JOIN LATERAL (
            SELECT pe, pb, roe, roce, debt_equity FROM fundamentals
            WHERE stock_id = s.id AND knowledge_to IS NULL ORDER BY period_end DESC LIMIT 1
        ) f ON true
        WHERE m.code = :market
    )
"""

_SCREEN_COLS = (
    "symbol",
    "company_name",
    "sector",
    "market_cap_bucket",
    "market",
    "composite_score",
    "fundamental_score",
    "momentum_score",
    "quality_score",
    "sentiment_score",
    "risk_score",
    "coverage",
    "pe",
    "pb",
    "roe",
    "roce",
    "debt_equity",
)
_SCREEN_NUMERIC = frozenset(_SCREEN_COLS[5:])


def _screener_row(r: Any) -> dict[str, object]:
    return {c: (_f(r[c]) if c in _SCREEN_NUMERIC else r[c]) for c in _SCREEN_COLS}


def screen(
    session: Session,
    *,
    market: str,
    where_sql: str,
    params: dict[str, object],
    order_sql: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    """Run a validated screener query. ``where_sql``/``order_sql`` are allow-list-built (trusted);
    every user value is a bound parameter. Returns (rows, total_match_count)."""
    sql = text(
        f"{_SCREEN_CTE}"
        "SELECT *, COUNT(*) OVER() AS total_count FROM screened "
        f"WHERE {where_sql} ORDER BY {order_sql} LIMIT :limit OFFSET :offset"
    )
    bound = {**params, "market": market, "limit": limit, "offset": offset}
    rows = session.execute(sql, bound).mappings().all()
    count = int(rows[0]["total_count"]) if rows else 0
    return [_screener_row(r) for r in rows], count

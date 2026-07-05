"""analytics — data access for scores + factor_values (QV-029).

Both tables are global (no RLS) and partitioned monthly → the **privileged** engine. Upserts are
keyed on the natural unique index so re-scoring a date never duplicates. Persists the ``StockScore``
decomposition: one ``factor_values`` row per stock×factor + one ``scores`` row per stock.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.analytics.scoring import StockScore

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


def upsert_factor_values(session: Session, scores: Sequence[StockScore]) -> int:
    """Upsert the per-factor decomposition (``ON CONFLICT (stock_id, date, factor_key)``)."""
    params = [
        {
            "stock_id": s.stock_id,
            "date": s.date,
            "factor_key": fv.factor_key,
            "raw_value": fv.raw_value,
            "zscore": fv.zscore,
            "percentile_sector": fv.percentile_sector,
            "percentile_universe": fv.percentile_universe,
        }
        for s in scores
        for fv in s.factor_values
    ]
    if not params:
        return 0
    session.execute(_UPSERT_FACTOR_VALUES_SQL, params)
    return len(params)

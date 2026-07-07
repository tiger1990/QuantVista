"""analytics — services layer (QV-031 cache-aside reads + QV-033 score decomposition).

Cache-aside rankings over the ``ICache`` seam (03 §8), plus ``decompose`` — per-factor contributions
that **sum to the composite** (US-02), reproducing the ScoreEngine blend from the stored snapshot.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session

from quantvista.analytics.factors import ALL_FACTORS, FactorCategory
from quantvista.analytics.repositories import factor_values_for, rankings_for, score_of
from quantvista.analytics.scoring import DEFAULT_WEIGHTS
from quantvista.core.cache import ICache
from quantvista.core.config import get_settings

_CATEGORY_OF: dict[str, FactorCategory] = {f.key: f.category for f in ALL_FACTORS}


def rankings_cache_key(market: str, as_of: date) -> str:
    return f"rank:{market}:{as_of.isoformat()}"


def cached_rankings(
    cache: ICache, session: Session, market: str, as_of: date
) -> list[dict[str, object]]:
    """Cache-aside ranked scores for ``market``/``as_of`` (03 §8): cache → DB → cache."""
    key = rankings_cache_key(market, as_of)
    hit = cache.get(key)
    if hit is not None:
        return list(hit)
    rows = rankings_for(session, market, as_of)
    cache.set(key, rows, ttl_seconds=get_settings().cache_ttl_seconds)
    return rows


def decompose(session: Session, symbol: str, as_of: date | None = None) -> dict[str, object] | None:
    """Per-factor contributions summing to the composite (US-02); ``None`` if unscored.

    Reproduces the ScoreEngine blend from ``factor_values``: contribution =
    (renorm_weight[category] / factors_in_category) × percentile_universe, so Σ == composite.
    """
    score = score_of(session, symbol, as_of)
    if score is None:
        return None
    stock_id = cast(UUID, score["stock_id"])
    score_date = cast(date, score["date"])
    fvs = factor_values_for(session, [stock_id], score_date).get(stock_id, [])

    counts = Counter(_CATEGORY_OF[fv.factor_key] for fv in fvs)
    weights = {cat: DEFAULT_WEIGHTS.of(cat) for cat in counts}
    total = sum(weights.values()) or 1.0  # re-normalize over scored categories

    factors: list[dict[str, object]] = []
    running = 0.0
    for fv in fvs:
        cat = _CATEGORY_OF[fv.factor_key]
        contribution = (weights[cat] / total) / counts[cat] * fv.percentile_universe
        running += contribution
        factors.append(
            {
                "factor_key": fv.factor_key,
                "category": cat.value,
                "raw_value": fv.raw_value,
                "zscore": fv.zscore,
                "percentile_sector": fv.percentile_sector,
                "percentile_universe": fv.percentile_universe,
                "contribution": contribution,
                "as_of": score_date.isoformat(),
            }
        )
    return {
        "symbol": symbol,
        "as_of": score_date.isoformat(),
        "composite": score["composite"],
        "sum_of_contributions": running,
        "factors": factors,
    }

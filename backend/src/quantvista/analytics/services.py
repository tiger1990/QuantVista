"""analytics — services layer (QV-031: cache-aside score/ranking reads).

Read-through over the ``ICache`` seam: return the cached rankings on hit, else read the DB, cache
under ``rank:{market}:{date}`` with the TTL backstop, and return. Invalidation is event-driven
(``ScoresComputed`` → ``jobs.consumers.on_scores_computed``). Cross-context calls go through seams.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from quantvista.analytics.repositories import rankings_for
from quantvista.core.cache import ICache
from quantvista.core.config import get_settings


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

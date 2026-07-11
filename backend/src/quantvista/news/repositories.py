"""news — persistence (QV-041, QV-042).

Writes to the global ``news`` table (0007). De-dup is by ``source_url`` via the partial unique index
``uq_news_source_url`` (``WHERE source_url IS NOT NULL``). ``stock_id`` is set by tagging (QV-042).
Stores derived fields + the link only — never full article text (``03`` §1 rule 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.news.models import NewsArticle, UntaggedArticle

# ON CONFLICT targets the partial index by repeating its predicate; DO NOTHING + RETURNING id lets
# us count only the rows that actually inserted (a duplicate URL returns no row).
_INSERT_NEWS_SQL = text(
    """
    INSERT INTO news (headline, summary, source, source_url, published_at, language)
    VALUES (:headline, :summary, :source, :source_url, :published_at, :language)
    ON CONFLICT (source_url) WHERE source_url IS NOT NULL DO NOTHING
    RETURNING id
    """
)


def upsert_news(session: Session, articles: Sequence[NewsArticle]) -> int:
    """Insert articles, de-duplicating on ``source_url``; returns the count actually inserted."""
    inserted = 0
    for article in articles:
        row = session.execute(
            _INSERT_NEWS_SQL,
            {
                "headline": article.headline,
                "summary": article.summary,
                "source": article.source,
                "source_url": article.source_url,
                "published_at": article.published_at,
                "language": article.language,
            },
        ).first()
        if row is not None:
            inserted += 1
    return inserted


_UNTAGGED_SQL = text(
    """
    SELECT id, headline, summary FROM news
    WHERE stock_id IS NULL
    ORDER BY published_at DESC
    LIMIT :limit
    """
)
_SET_STOCK_SQL = text("UPDATE news SET stock_id = :stock_id WHERE id = :id")


def iter_untagged_news(session: Session, limit: int = 5000) -> list[UntaggedArticle]:
    """The most-recent untagged articles (``stock_id IS NULL``) — the tagging work list."""
    rows = session.execute(_UNTAGGED_SQL, {"limit": limit}).all()
    return [UntaggedArticle(id=r[0], headline=r[1], summary=r[2]) for r in rows]


def set_news_stock(session: Session, news_id: UUID, stock_id: UUID) -> None:
    """Link one article to its matched stock (QV-042)."""
    session.execute(_SET_STOCK_SQL, {"stock_id": stock_id, "id": news_id})


# --- read models (QV-043 API) ------------------------------------------------
# Indian publishers ranked ahead of US-centric wire sources (Finnhub's Reuters/CNBC/Bloomberg) in
# the market-wide feed — kept, not dropped (US macro still matters), just sunk below Indian news.
_INDIA_SOURCES = (
    "economic times",
    "moneycontrol",
    "livemint",
    "mint",
    "businessline",
    "business standard",
    "times of india",
    "financial express",
    "business today",
    "ndtv",
    "cnbc tv18",
)
_INDIA_RANK_SQL = " OR ".join(f"lower(coalesce(source, '')) LIKE '%{s}%'" for s in _INDIA_SOURCES)

_NEWS_FOR_STOCK_SQL = text(
    """
    SELECT n.id, n.headline, n.summary, n.source, n.source_url, n.published_at
    FROM news n
    JOIN stocks s ON s.id = n.stock_id
    WHERE s.symbol = :symbol
      AND (CAST(:since AS date) IS NULL OR n.published_at >= :since)
    ORDER BY n.published_at DESC
    LIMIT :limit
    """
)
_LATEST_NEWS_SQL = text(
    f"""
    SELECT id, headline, summary, source, source_url, published_at
    FROM news
    WHERE (CAST(:since AS date) IS NULL OR published_at >= :since)
    ORDER BY ({_INDIA_RANK_SQL}) DESC, published_at DESC
    LIMIT :limit
    """  # noqa: S608 - _INDIA_RANK_SQL is a static allowlist constant, not user input
)


def _news_row(r: Any) -> dict[str, object]:
    return {
        "id": str(r["id"]),
        "headline": r["headline"],
        "summary": r["summary"],
        "source": r["source"],
        "source_url": r["source_url"],
        "published_at": r["published_at"],
    }


def news_for_stock(
    session: Session, symbol: str, *, since: date | None, limit: int
) -> list[dict[str, object]]:
    """A stock's tagged news, newest-first, on or after ``since`` (None = no lower bound)."""
    rows = (
        session.execute(_NEWS_FOR_STOCK_SQL, {"symbol": symbol, "since": since, "limit": limit})
        .mappings()
        .all()
    )
    return [_news_row(r) for r in rows]


def latest_news(session: Session, *, since: date | None, limit: int) -> list[dict[str, object]]:
    """Market-wide latest news, India-source-first then newest, on or after ``since``."""
    rows = session.execute(_LATEST_NEWS_SQL, {"since": since, "limit": limit}).mappings().all()
    return [_news_row(r) for r in rows]

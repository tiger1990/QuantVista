"""news — persistence (QV-041).

Writes to the global ``news`` table (0007). De-dup is by ``source_url`` via the partial unique index
``uq_news_source_url`` (``WHERE source_url IS NOT NULL``); ``stock_id`` stays NULL until tagging
(QV-042). Stores derived fields + the link only — never full article text (``03`` §1 rule 4).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.news.models import NewsArticle

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

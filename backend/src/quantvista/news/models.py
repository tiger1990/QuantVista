"""news — domain DTOs (QV-041).

Immutable value objects at the news boundary. ``NewsArticle`` is the provider-agnostic shape every
``INewsProvider`` returns and the repository persists — headline + short summary + link only, never
the full article text (``03`` §1 rule 4: store derived, link to original).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NewsArticle:
    """One ingested article (maps to a ``news`` row; ``stock_id`` NULL until tagging, QV-042)."""

    headline: str
    summary: str | None
    source: str | None
    source_url: str | None
    published_at: datetime
    language: str = "en"


@dataclass(frozen=True, slots=True)
class NewsIngestReport:
    """Outcome of one ``ingest_news`` run (aggregated across all fanned-out providers)."""

    providers: tuple[str, ...]
    since: datetime
    until: datetime
    fetched: int
    inserted: int
    fetches_failed: int = 0

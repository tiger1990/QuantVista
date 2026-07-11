"""news — domain DTOs (QV-041).

Immutable value objects at the news boundary. ``NewsArticle`` is the provider-agnostic shape every
``INewsProvider`` returns and the repository persists — headline + short summary + link only, never
the full article text (``03`` §1 rule 4: store derived, link to original).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

SentimentLabel = Literal["positive", "negative", "neutral"]


@dataclass(frozen=True, slots=True)
class SentimentResult:
    """One model's read of a single text (QV-044).

    ``score`` is signed in [-1, 1] (≈ P(pos) − P(neg)); ``confidence`` is [0, 1]. Money-rule
    Decimals (never float). Maps 1:1 to a ``sentiment`` row's label/score/confidence per model.
    """

    label: SentimentLabel
    score: Decimal
    confidence: Decimal


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


@dataclass(frozen=True, slots=True)
class UntaggedArticle:
    """An untagged article's matchable fields (QV-042 tagging work item)."""

    id: UUID
    headline: str
    summary: str | None


@dataclass(frozen=True, slots=True)
class TagReport:
    """Outcome of one ``tag_news`` run (QV-094 many-to-many)."""

    scanned: int  # articles processed this run
    tagged: int  # articles that matched ≥1 stock
    links: int  # total news↔stock links written


@dataclass(frozen=True, slots=True)
class UnscoredArticle:
    """An article with no ``sentiment`` row for the active model_version (QV-044 work item)."""

    id: UUID
    headline: str
    summary: str | None


@dataclass(frozen=True, slots=True)
class SentimentReport:
    """Outcome of one ``score_news`` run for a given model_version (QV-044)."""

    model_version: str
    scanned: int  # articles that needed scoring this run
    scored: int  # sentiment rows written (inserted or re-scored)

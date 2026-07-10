"""News & Sentiment published interfaces."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from quantvista.news.models import NewsArticle


@runtime_checkable
class INewsProvider(Protocol):
    """Vendor-agnostic source of news (the adapter boundary, QV-041).

    Every external news vendor enters ONLY through this interface, so swapping vendors
    (NewsAPI → Finnhub/GNews) is a new adapter with zero service/DB change. Returns the
    immutable ``NewsArticle`` DTO; ``since``/``until`` bound the fetch window.
    """

    def get_news(self, query: str, since: datetime, until: datetime) -> Sequence[NewsArticle]: ...


@runtime_checkable
class INewsService(Protocol):
    """News ingestion and per-stock tagging."""

    def latest_for_stock(self, stock_id: UUID, limit: int = 20) -> object: ...


@runtime_checkable
class ISentimentService(Protocol):
    """FinBERT-backed sentiment scoring for a piece of text."""

    def score(self, text: str) -> float: ...

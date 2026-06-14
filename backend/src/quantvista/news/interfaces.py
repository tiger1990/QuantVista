"""News & Sentiment published interfaces."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class INewsService(Protocol):
    """News ingestion and per-stock tagging."""

    def latest_for_stock(self, stock_id: UUID, limit: int = 20) -> object: ...


@runtime_checkable
class ISentimentService(Protocol):
    """FinBERT-backed sentiment scoring for a piece of text."""

    def score(self, text: str) -> float: ...

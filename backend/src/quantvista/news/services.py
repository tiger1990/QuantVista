"""news — ingestion service (QV-041).

Provider-agnostic **fan-out**: depends only on ``INewsProvider``, and runs a list of them (NewsAPI,
GNews, Marketaux, Finnhub) over a small fixed set of India-market queries, de-duplicating across all
sources on ``source_url``. Emits ``NewsIngested``; ``stock_id`` stays NULL — tagging to stocks is
QV-042. Per-(provider, query) isolation: one failing source/query never aborts the run.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import structlog
from sqlalchemy.orm import Session

from quantvista.core.db import privileged_session_scope
from quantvista.core.interfaces import IEventBus
from quantvista.news.interfaces import INewsProvider
from quantvista.news.models import NewsIngestReport, TagReport
from quantvista.news.repositories import (
    iter_untagged_news,
    link_news_stocks,
    mark_news_tagged,
    upsert_news,
)
from quantvista.news.tagging import StockRef, build_match_index, match_all

# Broad market queries (not per-stock — that would blow the free-tier cap; tagging is QV-042).
MARKET_QUERIES: tuple[str, ...] = (
    "NSE OR BSE OR Sensex OR Nifty",
    "Indian stock market",
)


class NewsIngestionService:
    """Fan out over the configured ``INewsProvider``s; emit ``NewsIngested`` (``06`` catalog)."""

    def __init__(self, providers: Sequence[INewsProvider], event_bus: IEventBus) -> None:
        self._providers = list(providers)
        self._events = event_bus
        self._log = structlog.get_logger()

    def ingest(self, since: datetime, until: datetime) -> NewsIngestReport:
        """Fetch every (provider × market query) over ``[since, until]``, dedup-upsert, publish."""
        fetched = inserted = failed = 0
        used: list[str] = []
        for provider in self._providers:
            name = str(getattr(provider, "name", "news"))
            used.append(name)
            for query in MARKET_QUERIES:
                try:
                    articles = provider.get_news(query, since, until)
                    fetched += len(articles)
                    with privileged_session_scope() as session:
                        inserted += upsert_news(session, articles)
                except Exception as exc:  # per-(provider, query) isolation — record and keep going
                    failed += 1
                    self._log.warning(
                        "news_fetch_failed", provider=name, query=query, error=str(exc)
                    )

        report = NewsIngestReport(tuple(used), since, until, fetched, inserted, failed)
        self._events.publish(
            "NewsIngested",
            {
                "providers": used,
                "since": since.isoformat(),
                "until": until.isoformat(),
                "fetched": fetched,
                "inserted": inserted,
            },
        )
        return report


class NewsTaggingService:
    """Tag unprocessed news to **every** stock it confidently names (QV-094) via the pure matcher.
    Each article is marked ``tagged_at`` once processed (so no-match rows aren't re-scanned); a
    multi-stock article links to all its stocks in ``news_stocks`` → shows on each stock's feed."""

    def __init__(self, catalog: Sequence[StockRef]) -> None:
        self._index = build_match_index(catalog)
        self._log = structlog.get_logger()

    def tag_untagged(self, session: Session, *, limit: int = 5000) -> TagReport:
        articles = iter_untagged_news(session, limit)
        tagged = links = 0
        for article in articles:
            text = article.headline + (f" {article.summary}" if article.summary else "")
            stock_ids = match_all(text, self._index)
            if stock_ids:
                links += link_news_stocks(session, article.id, stock_ids)
                tagged += 1
            mark_news_tagged(session, article.id)  # processed either way
        self._log.info("news_tagged", scanned=len(articles), tagged=tagged, links=links)
        return TagReport(scanned=len(articles), tagged=tagged, links=links)

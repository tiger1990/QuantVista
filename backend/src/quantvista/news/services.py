"""news — ingestion service (QV-041).

Provider-agnostic **fan-out**: depends only on ``INewsProvider``, and runs a list of them (NewsAPI,
GNews, Marketaux, Finnhub) over a small fixed set of India-market queries, de-duplicating across all
sources on ``source_url``. Emits ``NewsIngested``; ``stock_id`` stays NULL — tagging to stocks is
QV-042. Per-(provider, query) isolation: one failing source/query never aborts the run.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4

import structlog
from sqlalchemy.orm import Session

from quantvista.core.db import privileged_session_scope
from quantvista.core.interfaces import IEventBus
from quantvista.news.events import EventImpactScorer
from quantvista.news.interfaces import INewsProvider, ISentimentService
from quantvista.news.models import NewsIngestReport, SentimentReport, TagReport, UnscoredArticle
from quantvista.news.repositories import (
    iter_unscored_news,
    iter_untagged_news,
    link_news_stocks,
    mark_news_tagged,
    upsert_news,
    upsert_sentiment,
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


_DEFAULT_BATCH = 32


class SentimentScoringService:
    """Score unscored news with the active ``ISentimentService``; persist + emit ``NewsScored``.

    Model-agnostic (QV-044): the injected runtime is DevSentiment on the ``default`` queue or
    FinBERTSentiment on the ``nlp`` queue — this service only sees the seam. Work is batched (one
    ``classify`` call per ``batch_size`` texts) so a real model amortises tokenisation. In the same
    pass it derives each article's ``impact_score`` (QV-045: event type × sentiment) and persists
    both. Each batch commits in its own session scope; ``NewsScored`` fires once **after** the
    writes are durable.
    """

    def __init__(
        self,
        model: ISentimentService,
        event_bus: IEventBus,
        impact_scorer: EventImpactScorer | None = None,
    ) -> None:
        self._model = model
        self._events = event_bus
        self._impact = impact_scorer or EventImpactScorer()
        self._log = structlog.get_logger()

    def score_unscored(
        self,
        *,
        limit: int = 5000,
        batch_size: int = _DEFAULT_BATCH,
        batch_id: str | None = None,
    ) -> SentimentReport:
        model_version = self._model.model_version
        batch = batch_id or uuid4().hex
        with privileged_session_scope() as session:
            work = iter_unscored_news(session, model_version, limit)

        scored = 0
        for start in range(0, len(work), batch_size):
            chunk = work[start : start + batch_size]
            texts = [self._text(a) for a in chunk]
            results = self._model.classify(texts)
            rows = [
                (article.id, result, self._impact.score(text, result))
                for article, result, text in zip(chunk, results, texts, strict=True)
            ]
            with privileged_session_scope() as session:
                scored += upsert_sentiment(session, model_version, rows)

        self._events.publish(
            "NewsScored",
            {"news_batch": batch, "count": scored, "impact_version": self._impact.ruleset_version},
        )
        self._log.info(
            "news_scored",
            model_version=model_version,
            impact_version=self._impact.ruleset_version,
            scanned=len(work),
            scored=scored,
        )
        return SentimentReport(model_version=model_version, scanned=len(work), scored=scored)

    @staticmethod
    def _text(article: UnscoredArticle) -> str:
        return f"{article.headline} {article.summary or ''}".strip()

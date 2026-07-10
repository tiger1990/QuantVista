"""news jobs — ``ingest_news`` (QV-041) + ``tag_news`` (QV-042).

Under the QV-015 job framework (recorded in ``jobs_runs``). ``ingest_news`` fans out over the
enabled providers (emits ``NewsIngested``); ``tag_news`` links untagged articles to a ``stock_id``
via the pure ``news.tagging`` matcher, fed the stocks catalog read from ``market_data`` (this job is
the composition root — ``news`` itself never imports ``market_data``). Both off live Beat until a
scheduler (→ PV-007); ``tag_news`` also runs as a ``NewsIngested`` consumer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from quantvista.core.config import Settings, get_settings
from quantvista.core.db import privileged_session_scope
from quantvista.core.events import get_event_bus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.repositories import stock_catalog
from quantvista.news.interfaces import INewsProvider
from quantvista.news.providers import (
    FinnhubProvider,
    GNewsProvider,
    MarketauxProvider,
    NewsApiProvider,
)
from quantvista.news.services import NewsIngestionService, NewsTaggingService
from quantvista.news.tagging import StockRef

_log = structlog.get_logger()

NEWS_JOB_NAME = "ingest_news"
TAG_JOB_NAME = "tag_news"
# Fetch a window slightly wider than the hourly cadence so a delayed run never leaves a gap; the
# source_url dedup makes the overlap free.
_WINDOW = timedelta(hours=2)

# Registry: provider name → (adapter class, the settings attr holding its key). Add a vendor here +
# its key in Settings and it drops into the fan-out — zero service/DB change.
_REGISTRY: dict[str, tuple[type[INewsProvider], str]] = {
    "newsapi": (NewsApiProvider, "newsapi_org_api_key"),
    "gnews": (GNewsProvider, "gnews_api_key"),
    "marketaux": (MarketauxProvider, "marketaux_api_key"),
    "finnhub": (FinnhubProvider, "finnhub_api_key"),
}


def get_news_providers(settings: Settings | None = None) -> list[INewsProvider]:
    """Build every enabled provider (``news_providers``) that has a key set; skip the rest."""
    settings = settings or get_settings()
    enabled = [p.strip() for p in settings.news_providers.split(",") if p.strip()]
    providers: list[INewsProvider] = []
    for name in enabled:
        entry = _REGISTRY.get(name)
        if entry is None:
            raise RuntimeError(f"unknown news provider: {name!r}")
        cls, key_attr = entry
        key = getattr(settings, key_attr)
        if not key:
            _log.warning("news_provider_skipped_no_key", provider=name)
            continue
        providers.append(cls(key))  # type: ignore[call-arg]  # adapters share the (key) ctor
    return providers


def _run_news(until: datetime, key: str) -> JobOutcome:
    service = NewsIngestionService(get_news_providers(), get_event_bus())

    def work() -> JobResult:
        report = service.ingest(until - _WINDOW, until)
        return JobResult(rows_in=report.fetched, rows_out=report.inserted)

    return run_job(NEWS_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.ingest_news",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def ingest_news() -> str:
    """Hourly: ingest market news from all enabled providers (idempotent per hour bucket)."""
    now = datetime.now(UTC)
    key = run_key("news", now.strftime("%Y-%m-%dT%H"))
    return _run_news(now, key).status.value


def _run_tag(key: str) -> JobOutcome:
    def work() -> JobResult:
        with privileged_session_scope() as session:
            catalog = [
                StockRef(c.stock_id, c.symbol, c.isin, c.company_name)
                for c in stock_catalog(session)
            ]
            report = NewsTaggingService(catalog).tag_untagged(session)
        return JobResult(rows_in=report.scanned, rows_out=report.tagged)

    return run_job(TAG_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.tag_news",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def tag_news() -> str:
    """Tag untagged news to stocks (QV-042). Runs on ``NewsIngested`` + is manually triggerable.

    Keyed per-second (not per-day): each run tags whatever is *currently* untagged, so it must run
    after every ingest — the tagging itself is naturally idempotent (tagged rows are never re-read).
    """
    key = run_key("tag_news", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"))
    return _run_tag(key).status.value

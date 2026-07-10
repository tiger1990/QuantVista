"""ingest_news job (QV-041) — pull market news through the provider seam into ``news``.

Under the QV-015 job framework (``run_key = news:{provider}:{hour}``, recorded in ``jobs_runs``).
Provider-agnostic: ``get_news_provider`` picks the configured adapter (NewsAPI now; Finnhub/GNews
are drop-ins). Emits ``NewsIngested``; tagging to stocks is QV-042.

**Intended cadence: hourly.** Like prices/macro, this data job is kept **off live Beat** until a
``news_api_key`` + a live scheduler exist (→ PV-007); scheduling it now would spam failing, key-less
runs. Wire the hourly ``crontab(minute=0)`` entry into ``beat_schedule`` at that point.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from quantvista.core.config import Settings, get_settings
from quantvista.core.events import get_event_bus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.news.interfaces import INewsProvider
from quantvista.news.providers import (
    FinnhubProvider,
    GNewsProvider,
    MarketauxProvider,
    NewsApiProvider,
)
from quantvista.news.services import NewsIngestionService

_log = structlog.get_logger()

NEWS_JOB_NAME = "ingest_news"
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

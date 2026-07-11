"""sentiment job — ``score_news`` (QV-044) on the dedicated ``nlp`` queue.

The composition root for sentiment scoring: it picks the runtime from ``Settings.sentiment_model``
(``dev`` → DevSentiment, ``finbert`` → FinBERTSentiment) and runs it under the QV-015 job framework
(recorded in ``jobs_runs``). Routed to the ``nlp`` queue (``celery_app`` ``task_routes``) so a
capable host can run ``celery -A quantvista.jobs.celery_app worker -Q nlp`` with the ``[finbert]``
extra while the dev box / CI run the ``default`` queue. Off live Beat until a scheduler (→ PV-007);
manually triggerable and safe to re-run (idempotent per (news, model_version)).
"""

from __future__ import annotations

from datetime import UTC, datetime

from quantvista.core.config import Settings, get_settings
from quantvista.core.events import get_event_bus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.news.interfaces import ISentimentService
from quantvista.news.sentiment import DevSentiment
from quantvista.news.services import SentimentScoringService

SENTIMENT_JOB_NAME = "score_news"


def get_sentiment_model(settings: Settings | None = None) -> ISentimentService:
    """Build the sentiment runtime named by ``sentiment_model`` (dev by default)."""
    settings = settings or get_settings()
    choice = settings.sentiment_model.strip().casefold()
    if choice == "dev":
        return DevSentiment()
    if choice == "finbert":
        # Imported lazily so the heavy [finbert] extra is only touched when actually selected.
        from quantvista.news.adapters.finbert import FinBERTSentiment  # noqa: PLC0415

        return FinBERTSentiment()
    raise RuntimeError(f"unknown sentiment_model: {settings.sentiment_model!r} (want dev|finbert)")


def _run_score(key: str, batch_id: str) -> JobOutcome:
    service = SentimentScoringService(get_sentiment_model(), get_event_bus())

    def work() -> JobResult:
        report = service.score_unscored(batch_id=batch_id)
        return JobResult(rows_in=report.scanned, rows_out=report.scored)

    return run_job(SENTIMENT_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.score_news",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def score_news() -> str:
    """Score whatever news is currently unscored for the active model (QV-044).

    Keyed per-second (like ``tag_news``): each run scores whatever lacks a row for this
    ``model_version`` — naturally idempotent (scored rows are never re-read). The bucket also seeds
    the ``NewsScored`` batch id so the event is traceable to this run.
    """
    bucket = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    key = run_key("score_news", bucket)
    return _run_score(key, batch_id=key).status.value

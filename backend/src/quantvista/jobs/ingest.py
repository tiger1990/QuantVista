"""Daily-price ingestion task + backfill (QV-016).

Wires the yfinance dev provider + its Yahoo symbol mapper + the logging event bus into
``PriceIngestionService``, and runs it under the QV-015 job framework (``run_key =
prices:{market}:{date}``, idempotent, recorded in ``jobs_runs``). Strict failure policy: if
any stock failed unexpectedly the job **raises** so ``run_job`` marks the run failed → retry.
Backfill replays the same task over a date window (``06`` §1.3: backfill = same code).
"""

from __future__ import annotations

from datetime import date

from quantvista.core.events import LoggingEventBus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.adapters.yfinance_dev import YFinanceDevProvider, yahoo_symbol
from quantvista.market_data.services import PriceIngestionService
from quantvista.market_data.trading_calendar import last_completed_session

JOB_NAME = "ingest_daily_prices"


class IngestRunFailed(RuntimeError):
    """Raised (strict policy) when >=1 stock failed unexpectedly, to fail the job for retry."""


def _run(market: str, start: date, end: date, key: str, index_code: str) -> JobOutcome:
    provider = YFinanceDevProvider()
    service = PriceIngestionService(provider, LoggingEventBus(), symbol_mapper=yahoo_symbol)

    def work() -> JobResult:
        report = service.ingest(market, start, end, index_code=index_code)
        if report.stocks_failed:  # STRICT: any unexpected failure fails the run → retry
            raise IngestRunFailed(
                f"{report.stocks_failed}/{report.stocks_total} stocks failed: "
                f"{[s for s, _ in report.failures][:10]}"
            )
        return JobResult(rows_in=report.stocks_ok, rows_out=report.rows_upserted)

    return run_job(JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.ingest_daily_prices",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def ingest_daily_prices(market: str = "NSE", date_iso: str | None = None) -> str:
    """Ingest the last completed session (or an explicit ``date_iso``) for ``market``."""
    target = date.fromisoformat(date_iso) if date_iso else last_completed_session(date.today())
    key = run_key("prices", market, target.isoformat())
    return _run(market, target, target, key, "NIFTY200").status.value


def backfill_daily_prices(
    market: str = "NSE", *, start: date, end: date, index_code: str = "NIFTY200"
) -> JobOutcome:
    """One-off historical backfill over ``[start, end]`` — the same per-stock upsert path.

    Operational (not scheduled): e.g. an initial 5-year load. One provider call per stock over
    the window; idempotent via the ``(stock_id, date)`` upsert + the range run_key.
    """
    key = run_key("prices", market, "backfill", start.isoformat(), end.isoformat())
    return _run(market, start, end, key, index_code)

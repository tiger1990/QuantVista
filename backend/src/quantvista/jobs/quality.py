"""Data-quality gate task (QV-018).

Runs the post-ingestion gates (``DataQualityService``) under the QV-015 job framework
(``run_key = dq:prices:{market}:{date}``, recorded in ``jobs_runs``). Strict policy: a failed
gate **raises** ``DataQualityGateError`` so ``run_job`` marks the run ``failed`` and the pipeline
halts — no ``PricesValidated`` is emitted, so downstream (indicators/factors) never fires. The
service has already emitted ``DataQualityGateFailed`` as the alert seam. Range mode shares the code.
"""

from __future__ import annotations

from datetime import date

from quantvista.core.events import get_event_bus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.services import DataQualityService
from quantvista.market_data.trading_calendar import last_completed_session

VALIDATE_JOB_NAME = "validate_prices"


class DataQualityGateError(RuntimeError):
    """Raised (strict) when a gate fails, to fail the run and halt downstream."""


def _run_validate(market: str, start: date, end: date, key: str, index_code: str) -> JobOutcome:
    service = DataQualityService(get_event_bus())

    def work() -> JobResult:
        report = service.validate(market, start, end, index_code=index_code)
        if not report.passed:  # STRICT: a failed gate fails the run → downstream halts
            gates = ", ".join(v.gate for v in report.violations)
            raise DataQualityGateError(f"data-quality gate(s) failed: {gates}")
        return JobResult(rows_in=report.stocks_validated, rows_out=report.expected_stocks)

    return run_job(VALIDATE_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.validate_prices",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def validate_prices(market: str = "NSE", date_iso: str | None = None) -> str:
    """Validate the last completed session (or an explicit ``date_iso``) for ``market``."""
    target = date.fromisoformat(date_iso) if date_iso else last_completed_session(date.today())
    key = run_key("dq", "prices", market, target.isoformat())
    return _run_validate(market, target, target, key, "NIFTY200").status.value


def validate_prices_range(
    market: str = "NSE", *, start: date, end: date, index_code: str = "NIFTY200"
) -> JobOutcome:
    """One-off validation over ``[start, end]`` — the same gate path (e.g. after a backfill)."""
    key = run_key("dq", "prices", market, "backfill", start.isoformat(), end.isoformat())
    return _run_validate(market, start, end, key, index_code)

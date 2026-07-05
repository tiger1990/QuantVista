"""Correction-handling recompute seam (QV-027) — the self-heal insertion point.

When a fundamentals revision lands (``FundamentalsRevised``), the affected ``(stock, period_end)``
must have its derived analytics recomputed so scores don't stay stale (``06`` §5). This task is the
**seam Epic 4 fills** with the real ``compute_factors`` / ``compute_scores`` calls — for now it runs
under the QV-015 job framework (records ``jobs_runs``) and logs the correction, so the self-heal
loop is real + testable end-to-end before the scoring math exists.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import structlog

from quantvista.core.db import privileged_session_scope
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.jobs.scoring import compute_factors
from quantvista.market_data.repositories import stock_market
from quantvista.market_data.trading_calendar import last_completed_session

RECOMPUTE_JOB_NAME = "recompute_on_correction"
_log = structlog.get_logger()


def _run_recompute(stock_id: str, period_end: str, statement_type: str, key: str) -> JobOutcome:
    def work() -> JobResult:
        # Self-heal (QV-030): invalidate + recompute the market's factor SNAPSHOT for the current
        # cross-section → cascades to compute_scores. Cross-sectional, so one stock's correction
        # refreshes the whole universe. (Re-scoring historical dates is a future enhancement.)
        with privileged_session_scope() as session:
            market = stock_market(session, UUID(stock_id))
        _log.info("correction_recompute", stock_id=stock_id, period_end=period_end, market=market)
        if market is not None:
            compute_factors.delay(market, last_completed_session(date.today()).isoformat())
        return JobResult(rows_in=1, rows_out=0)

    return run_job(RECOMPUTE_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.recompute_on_correction",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def recompute_on_correction(
    stock_id: str, period_end: str, statement_type: str = "quarterly"
) -> str:
    """Recompute derived analytics for a corrected filing (Epic-4 factors/scores plug in here)."""
    date.fromisoformat(period_end)  # validate the affected date at the boundary
    key = run_key("recompute", stock_id, period_end)
    return _run_recompute(stock_id, period_end, statement_type, key).status.value

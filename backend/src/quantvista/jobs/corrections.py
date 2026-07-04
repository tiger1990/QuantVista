"""Correction-handling recompute seam (QV-027) — the self-heal insertion point.

When a fundamentals revision lands (``FundamentalsRevised``), the affected ``(stock, period_end)``
must have its derived analytics recomputed so scores don't stay stale (``06`` §5). This task is the
**seam Epic 4 fills** with the real ``compute_factors`` / ``compute_scores`` calls — for now it runs
under the QV-015 job framework (records ``jobs_runs``) and logs the correction, so the self-heal
loop is real + testable end-to-end before the scoring math exists.
"""

from __future__ import annotations

from datetime import date

import structlog

from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger

RECOMPUTE_JOB_NAME = "recompute_on_correction"
_log = structlog.get_logger()


def _run_recompute(stock_id: str, period_end: str, statement_type: str, key: str) -> JobOutcome:
    def work() -> JobResult:
        # Epic 4 fills this in: compute_factors(stock_id, period_end) → compute_scores(...) for the
        # dates whose scores consumed the revised filing. Until then, record the correction intent.
        _log.info(
            "correction_recompute",
            stock_id=stock_id,
            period_end=period_end,
            statement_type=statement_type,
        )
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

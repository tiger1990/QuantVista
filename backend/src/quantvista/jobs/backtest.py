"""Async backtest runner (QV-062).

Triggered by ``POST /backtests`` via ``run_backtest.delay(id)``. Runs on a **privileged session**
(background job, bypasses RLS — like the QV-048/049 alert jobs), moves the row queued→running then
succeeded/failed, and logs through the ``run_job`` ledger. Idempotent twice over: the ledger skips a
re-run of a succeeded ``run_key``, and ``mark_running`` only fires on a still-``queued`` row (Celery
is at-least-once). The compute itself is the QV-065 engine seam (placeholder today).
"""

from __future__ import annotations

from uuid import UUID

from quantvista.analytics.backtest import BacktestEngine
from quantvista.analytics.backtests import (
    get_backtest,
    mark_failed,
    mark_running,
    mark_succeeded,
)
from quantvista.core.db import privileged_session_scope
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.schemas.backtest import BacktestSpec


def _run(backtest_id: UUID) -> JobResult:
    with privileged_session_scope() as session:
        if not mark_running(session, backtest_id):
            return JobResult(rows_in=0, rows_out=0)  # not queued (already handled) → no-op
        row = get_backtest(session, backtest_id)
        assert row is not None  # mark_running succeeded ⇒ the row exists
        try:
            spec = BacktestSpec.model_validate(row["spec"])
            result = BacktestEngine().run(spec)  # QV-065 fills the real compute
            mark_succeeded(
                session, backtest_id, metrics=result.metrics, result_ref=result.result_ref
            )
        except Exception as exc:  # a bad spec / engine error marks the backtest failed (no retry)
            mark_failed(session, backtest_id, error=str(exc))
        return JobResult(rows_in=1, rows_out=1)


@app.task(
    name="quantvista.run_backtest",
    autoretry_for=(Exception,),  # infra errors (DB down) retry; engine failures are caught above
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def run_backtest(backtest_id: str) -> str:
    """Execute the queued backtest ``backtest_id`` and record its terminal status."""
    bid = UUID(backtest_id)
    return run_job(
        "run_backtest", run_key("backtest", backtest_id), lambda: _run(bid), ledger=JobRunLedger()
    ).status.value


__all__ = ["run_backtest"]

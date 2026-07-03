"""Universe sync tasks (QV-019).

Keeps the security master (`sync_stock_master`) and index membership (`sync_index_constituents`)
current under the QV-015 job framework. Master upsert is non-destructive; constituent sync is a
survivorship-free PIT reconcile. Strict: an unresolved constituent (a member with no `stocks` row —
master hasn't caught up) raises `UniverseSyncError` so the run is marked `failed` and nothing runs
on a half-known universe.

NOT scheduled on beat: the dev provider's `list_universe` is a non-authoritative 5-symbol stub, so
running the reconcile against it would wrongly close seeded members. The authoritative NIFTY-200 +
weights arrive with the licensed vendor (QV-072); scheduling is a later wiring step (→ PV-005).
"""

from __future__ import annotations

from datetime import date

from quantvista.core.events import LoggingEventBus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.adapters.yfinance_dev import YFinanceDevProvider
from quantvista.market_data.services import UniverseSyncService
from quantvista.market_data.trading_calendar import last_completed_session

MASTER_JOB_NAME = "sync_stock_master"
CONSTITUENTS_JOB_NAME = "sync_index_constituents"


class UniverseSyncError(RuntimeError):
    """Raised (strict) when a constituent can't be resolved to a stock, to fail the run."""


def _service() -> UniverseSyncService:
    return UniverseSyncService(YFinanceDevProvider(), LoggingEventBus())


def _run_master(market: str, index_code: str, key: str) -> JobOutcome:
    def work() -> JobResult:
        report = _service().sync_stock_master(market, index_code=index_code)
        return JobResult(rows_in=report.provider_count, rows_out=report.inserted + report.updated)

    return run_job(MASTER_JOB_NAME, key, work, ledger=JobRunLedger())


def _run_constituents(index_code: str, market: str, as_of: date, key: str) -> JobOutcome:
    def work() -> JobResult:
        report = _service().sync_index_constituents(index_code, market, as_of)
        if report.unresolved:  # STRICT: master must run first — fail loud, nothing mutated
            raise UniverseSyncError(
                f"{len(report.unresolved)} unresolved constituents: {report.unresolved[:10]}"
            )
        return JobResult(rows_in=report.provider_count, rows_out=report.added + report.closed)

    return run_job(CONSTITUENTS_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.sync_stock_master",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def sync_stock_master(market: str = "NSE", index_code: str = "NIFTY200") -> str:
    """Upsert the security master for ``market`` from the provider's universe (weekly/on demand)."""
    key = run_key("master", market, date.today().strftime("%G-W%V"))
    return _run_master(market, index_code, key).status.value


@app.task(
    name="quantvista.sync_index_constituents",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def sync_index_constituents(
    index_code: str = "NIFTY200", market: str = "NSE", date_iso: str | None = None
) -> str:
    """PIT-reconcile ``index_code`` membership to the provider's current set (on reconstitution)."""
    as_of = date.fromisoformat(date_iso) if date_iso else last_completed_session(date.today())
    key = run_key("constituents", index_code, as_of.isoformat())
    return _run_constituents(index_code, market, as_of, key).status.value


def sync_index_constituents_now(index_code: str, market: str, *, as_of: date) -> JobOutcome:
    """Direct (non-Celery) invocation for a one-off reconcile / tests — same guarded run path."""
    key = run_key("constituents", index_code, as_of.isoformat())
    return _run_constituents(index_code, market, as_of, key)

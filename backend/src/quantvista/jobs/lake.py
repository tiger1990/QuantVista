"""Parquet offload job (QV-067) — export historical prices to the data lake.

Runs on the ``compute`` queue; reads ``daily_prices`` on a privileged session (global reference,
no RLS) and writes monthly Parquet partitions to the configured object store (local-fs dev, S3/MinIO
in cloud). Idempotent (partition files overwritten) + ledger-guarded via ``run_job``.
"""

from __future__ import annotations

from datetime import date

from quantvista.core.config import get_settings
from quantvista.core.db import privileged_session_scope
from quantvista.core.objectstore import get_object_store
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.lake import export_prices_parquet as _export


@app.task(
    name="quantvista.export_prices_parquet",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def export_prices_parquet(market: str = "NSE") -> str:
    """Offload ``market``'s ``daily_prices`` to Parquet partitions (idempotent)."""
    store = get_object_store(get_settings())

    def work() -> JobResult:
        with privileged_session_scope() as session:
            rows = _export(session, store, market)
        return JobResult(rows_in=rows, rows_out=rows)

    key = run_key("parquet_prices", market, date.today().isoformat())
    return run_job("export_prices_parquet", key, work, ledger=JobRunLedger()).status.value


__all__ = ["export_prices_parquet"]

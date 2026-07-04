"""sync_macro_series job (QV-026) — pull a macro series from FRED into ``macro_series``.

Under the QV-015 job framework (``run_key = macro:{series}:{date}``, recorded in ``jobs_runs``).
No event (the ``06`` catalog emits none for macro). Not scheduled on beat (→ PV-006 cadence).
"""

from __future__ import annotations

from datetime import date, timedelta

from quantvista.core.config import get_settings
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.macro import (
    FRED_SERIES,
    FredMacroProvider,
    IMacroProvider,
    MacroSeries,
    WorldBankMacroProvider,
)
from quantvista.market_data.services import MacroSyncService

MACRO_JOB_NAME = "sync_macro_series"
# Wide window: annual World Bank series (India) lag >1yr, so a short window would miss them. The
# idempotent upsert makes re-writing ~5y of points each run cheap, keeping all series current.
_LOOKBACK_DAYS = 1825


def _provider_for(series: MacroSeries) -> IMacroProvider:
    """Route a canonical series to its source: FRED (US/global) or World Bank (India/global)."""
    if series in FRED_SERIES:
        return FredMacroProvider(get_settings().fred_api_key)
    return WorldBankMacroProvider()  # India / cross-country — no API key


def _run_macro(series: MacroSeries, start: date, end: date, key: str) -> JobOutcome:
    service = MacroSyncService(_provider_for(series))

    def work() -> JobResult:
        report = service.sync(series, start, end)
        return JobResult(rows_in=1, rows_out=report.observations_upserted)

    return run_job(MACRO_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.sync_macro_series",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def sync_macro_series(series: str = "US_10Y", date_iso: str | None = None) -> str:
    """Sync one macro series (a ``MacroSeries`` name) up to ``date`` (default today)."""
    target = date.fromisoformat(date_iso) if date_iso else date.today()
    resolved = MacroSeries(series)
    key = run_key("macro", resolved.value, target.isoformat())
    return _run_macro(resolved, target - timedelta(days=_LOOKBACK_DAYS), target, key).status.value

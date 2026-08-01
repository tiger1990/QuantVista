"""compute_indicators job (QV-025) — the first event-driven compute step.

Triggered by ``PricesValidated`` (gate-passed). Loads the active universe's adjusted-price history,
runs the Polars indicator math, and upserts ``technical_indicators`` (idempotent per (stock, date)).
Under the QV-015 job framework; emits ``IndicatorsComputed``.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import polars as pl

from quantvista.core.db import privileged_session_scope
from quantvista.core.events import get_event_bus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.indicators import INDICATOR_COLUMNS, compute_indicators_for_date
from quantvista.market_data.repositories import (
    active_universe,
    price_history_for_indicators,
    upsert_technical_indicators,
)
from quantvista.market_data.trading_calendar import last_completed_session, sessions_in_range

COMPUTE_JOB_NAME = "compute_indicators"
_LOOKBACK_SESSIONS = 300  # ≥ 252 (12M / beta) + buffer


def _clean(value: object) -> object:
    """Polars NaN → None (Postgres numeric rejects NaN); pass floats/None through."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _run_compute(market: str, target: date, key: str, index_code: str) -> JobOutcome:
    def work() -> JobResult:
        with privileged_session_scope() as session:
            universe = active_universe(session, index_code, market)
            stock_ids = [s.stock_id for s in universe]
            history = price_history_for_indicators(session, stock_ids, target, _LOOKBACK_SESSIONS)

        if not history:
            _emit(market, target, 0)
            return JobResult(rows_in=len(stock_ids), rows_out=0)

        frame = pl.DataFrame([{**row, "stock_id": str(row["stock_id"])} for row in history])
        out = compute_indicators_for_date(frame, target)

        from uuid import UUID

        rows = [
            {
                "stock_id": UUID(d["stock_id"]),
                "date": d["date"],
                **{c: _clean(d[c]) for c in INDICATOR_COLUMNS},
            }
            for d in out.to_dicts()
        ]
        with privileged_session_scope() as session:
            written = upsert_technical_indicators(session, rows)
        _emit(market, target, written)
        return JobResult(rows_in=len(stock_ids), rows_out=written)

    return run_job(COMPUTE_JOB_NAME, key, work, ledger=JobRunLedger())


def _emit(market: str, target: date, stocks: int) -> None:
    get_event_bus().publish(
        "IndicatorsComputed", {"market": market, "date": target.isoformat(), "stocks": stocks}
    )


@app.task(
    name="quantvista.compute_indicators",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def compute_indicators(market: str = "NSE", date_iso: str | None = None) -> str:
    """Compute + upsert technical indicators for ``market`` on ``date`` (default last session)."""
    target = date.fromisoformat(date_iso) if date_iso else last_completed_session(date.today())
    key = run_key("ind", market, target.isoformat())
    return _run_compute(market, target, key, "NIFTY200").status.value


def backfill_indicators(
    market: str = "NSE",
    *,
    start: date,
    end: date,
    index_code: str = "NIFTY200",
    force: bool = False,
) -> list[JobOutcome]:
    """Compute indicators for **every trading session** in ``[start, end]`` (QV-105).

    Indicators are the input the backtest engine ranks on, and they are computed *per date* — so a
    range of prices with a single date of indicators produces a backtest that silently holds
    nothing and reports 0.00% on every strategy metric while the benchmark looks healthy. Prices
    have had a range backfill since QV-016; this gives the derived step the same reach.

    Skips dates already recorded as succeeded (the QV-015 ledger), so an interrupted run resumes
    cheaply. That skip has a sharp edge worth knowing: a date whose original run wrote **partial**
    data — fewer stocks priced then than now — is considered done and will not be revisited.
    ``force=True`` re-runs regardless, recording each repair as its own ledger entry so the
    provenance of "we recomputed this date later" is kept rather than overwritten.

    Returns one outcome per session, oldest first.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") if force else None
    outcomes = []
    for session in sessions_in_range(start, end):
        parts = ["ind", market, session.isoformat()]
        if stamp:  # a distinct key per repair run — the ledger must not dedupe a deliberate redo
            parts += ["repair", stamp]
        outcomes.append(_run_compute(market, session, run_key(*parts), index_code))
    return outcomes

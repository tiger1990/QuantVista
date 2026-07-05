"""compute_factors + compute_scores jobs (QV-030) — factors canonical, scores projection.

The event-chained scoring stage (``06`` §3): ``compute_factors`` computes + persists the canonical
``factor_values`` snapshot then emits ``FactorsComputed``; ``compute_scores`` reads that committed
snapshot, blends it, persists ``scores`` then emits ``ScoresComputed``. **Events fire only after the
commit** (no phantom events). Both idempotent per ``(market, date)`` under the QV-015 job framework.
"""

from __future__ import annotations

from datetime import date

from quantvista.analytics.repositories import (
    factor_values_for,
    upsert_factor_values,
    upsert_scores,
)
from quantvista.analytics.scoring import MODEL_VERSION, FactorEngine, ScoreEngine
from quantvista.core.db import privileged_session_scope
from quantvista.core.events import get_event_bus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.repositories import active_universe
from quantvista.market_data.trading_calendar import last_completed_session

_INDEX = "NIFTY200"


def _default_date(date_iso: str | None) -> date:
    return date.fromisoformat(date_iso) if date_iso else last_completed_session(date.today())


def _run_factors(market: str, target: date, key: str) -> JobOutcome:
    def work() -> JobResult:
        with privileged_session_scope() as session:  # read + compute + write in one txn
            ids = [u.stock_id for u in active_universe(session, _INDEX, market)]
            snapshot = FactorEngine().compute_factor_values(session, ids, target)
            written = upsert_factor_values(session, target, snapshot)
        # commit has happened (scope exit; snapshot written atomically) → announce durable state.
        get_event_bus().publish(
            "FactorsComputed",
            {
                "market": market,
                "date": target.isoformat(),
                "model_version": MODEL_VERSION,
                "stock_count": len(snapshot),
                "factor_count": written,
            },
        )
        return JobResult(rows_in=len(ids), rows_out=written)

    return run_job("compute_factors", key, work, ledger=JobRunLedger())


def _run_scores(market: str, target: date, key: str) -> JobOutcome:
    def work() -> JobResult:
        with privileged_session_scope() as session:
            ids = [u.stock_id for u in active_universe(session, _INDEX, market)]
            snapshot = factor_values_for(session, ids, target)  # a committed factor snapshot
            scores = ScoreEngine().compute_scores(snapshot, target)
            written = upsert_scores(session, scores)
        get_event_bus().publish(
            "ScoresComputed",
            {
                "universe": market,
                "date": target.isoformat(),
                "model_version": MODEL_VERSION,
                "count": written,
            },
        )
        return JobResult(rows_in=len(snapshot), rows_out=written)

    return run_job("compute_scores", key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.compute_factors",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def compute_factors(market: str = "NSE", date_iso: str | None = None) -> str:
    """Compute + persist the factor snapshot for ``market`` on ``date`` (default last session)."""
    target = _default_date(date_iso)
    return _run_factors(market, target, run_key("fac", market, target.isoformat())).status.value


@app.task(
    name="quantvista.compute_scores",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def compute_scores(market: str = "NSE", date_iso: str | None = None) -> str:
    """Blend the persisted factor snapshot into scores for ``market`` on ``date``."""
    target = _default_date(date_iso)
    return _run_scores(market, target, run_key("score", market, target.isoformat())).status.value

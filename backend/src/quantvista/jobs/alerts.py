"""alerts job — ``evaluate_alerts`` (QV-048).

Event-triggered (``ScoresComputed`` / ``NewsScored`` → thin consumers ``.delay()`` it), so rules
fire within one scoring cycle (US-05). Cross-tenant on the privileged session (see
``AlertEvaluationService``); recorded under the QV-015 job framework, idempotent per
``(date, trigger)``. Emits ``AlertsFired`` after the events commit. Delivery is QV-049.
"""

from __future__ import annotations

from datetime import date

from quantvista.alerts.services import AlertEvaluationService
from quantvista.core.events import get_event_bus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.trading_calendar import last_completed_session

ALERTS_JOB_NAME = "evaluate_alerts"


def _run(as_of: date, trigger: str, key: str) -> JobOutcome:
    def work() -> JobResult:
        fired = AlertEvaluationService().evaluate(as_of, trigger)
        # Events are committed inside evaluate() → announce durable state (no phantom event).
        get_event_bus().publish(
            "AlertsFired", {"date": as_of.isoformat(), "trigger": trigger, "count": fired}
        )
        return JobResult(rows_in=0, rows_out=fired)

    return run_job(ALERTS_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.evaluate_alerts",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def evaluate_alerts(date_iso: str | None = None, trigger: str = "scores") -> str:
    """Evaluate all tenants' active rules for the cycle; write deduped events + emit AlertsFired."""
    as_of = date.fromisoformat(date_iso) if date_iso else last_completed_session(date.today())
    key = run_key("alerts", as_of.isoformat(), trigger)
    return _run(as_of, trigger, key).status.value

"""alerts job — ``evaluate_alerts`` (QV-048).

Event-triggered (``ScoresComputed`` / ``NewsScored`` → thin consumers ``.delay()`` it), so rules
fire within one scoring cycle (US-05). Cross-tenant on the privileged session (see
``AlertEvaluationService``); recorded under the QV-015 job framework, idempotent per
``(date, trigger)``. Emits ``AlertsFired`` after the events commit. Delivery is QV-049.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from quantvista.alerts.services import AlertEvaluationService, NotificationDeliveryService
from quantvista.core.events import get_event_bus
from quantvista.jobs.celery_app import app
from quantvista.jobs.framework import JobOutcome, JobResult, run_job, run_key
from quantvista.jobs.ledger import JobRunLedger
from quantvista.market_data.trading_calendar import last_completed_session

ALERTS_JOB_NAME = "evaluate_alerts"
DELIVER_JOB_NAME = "deliver_notifications"


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


def _run_deliver(key: str) -> JobOutcome:
    def work() -> JobResult:
        delivered = NotificationDeliveryService().deliver_pending()
        return JobResult(rows_in=0, rows_out=delivered)

    return run_job(DELIVER_JOB_NAME, key, work, ledger=JobRunLedger())


@app.task(
    name="quantvista.deliver_notifications",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def deliver_notifications() -> str:
    """Deliver pending/failed alert events via their channel (QV-049). Runs on ``AlertsFired``.

    Keyed per-second (like ``tag_news``) so each event re-evaluation delivers new events AND
    re-attempts failed ones — the retry — with delivery status per event.
    """
    key = run_key("deliver", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"))
    return _run_deliver(key).status.value

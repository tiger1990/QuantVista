"""Alert evaluation (QV-048) — cross-tenant, deduplicated, PIT-free (fires on current state).

Runs as a background job on the **privileged (RLS-bypassing) session**: reads every tenant's active
rules, evaluates each against the target stock's latest score/fundamentals snapshot, and writes an
``alert_events`` row when the condition holds — at most one per ``(rule, cycle date)`` via the 0010
dedup unique. Returns the number of NEW events; the caller (the job) emits ``AlertsFired``.
"""

from __future__ import annotations

from datetime import date

import structlog

from quantvista.alerts.channels import EmailChannel, InAppChannel
from quantvista.alerts.email import IEmailSender, get_email_sender
from quantvista.alerts.evaluation import matches
from quantvista.alerts.interfaces import DeliveryTarget, INotificationChannel
from quantvista.alerts.repositories import (
    active_alert_rules,
    insert_alert_event,
    mark_alert_event,
    pending_alert_events,
    stock_metrics,
)
from quantvista.core.db import privileged_session_scope


class AlertEvaluationService:
    """Evaluate all tenants' active alert rules for one cycle; write deduped ``alert_events``."""

    def __init__(self) -> None:
        self._log = structlog.get_logger()

    def evaluate(self, as_of: date, trigger: str) -> int:
        """Fire matching rules for the ``as_of`` cycle; returns the count of NEW events."""
        dedup_key = as_of.isoformat()
        with privileged_session_scope() as session:
            rules = [r for r in active_alert_rules(session) if r["scope"] == "stock"]
            metrics = stock_metrics(session, [r["target_id"] for r in rules])

            fired = 0
            for rule in rules:
                cond = rule["condition"]
                value = metrics.get(rule["target_id"], {}).get(cond["metric"])
                if not matches(value, cond["op"], float(cond["value"])):
                    continue
                payload = {
                    "type": "metric_alert",
                    "symbol": rule.get("target_symbol"),
                    "company_name": rule.get("company_name"),
                    "metric": cond["metric"],
                    "op": cond["op"],
                    "threshold": cond["value"],
                    "value": value,
                    "trigger": trigger,
                }
                if insert_alert_event(
                    session,
                    tenant_id=rule["tenant_id"],
                    alert_rule_id=rule["id"],
                    dedup_key=dedup_key,
                    payload=payload,
                ):
                    fired += 1

        self._log.info("alerts_evaluated", trigger=trigger, cycle=dedup_key, fired=fired)
        return fired


class NotificationDeliveryService:
    """Deliver pending ``alert_events`` (QV-049) via each event's rule channel; per-event status.

    Cross-tenant on the privileged session (like the evaluator). Each event is delivered inside a
    SAVEPOINT so one failure marks only that event ``failed`` (and rolls back its partial write)
    without aborting the run — a later run re-attempts ``failed`` events (the retry).
    """

    def __init__(self, email_sender: IEmailSender | None = None) -> None:
        # Default to the configured provider (EMAIL_PROVIDER); tests inject a spy/fake.
        self._email_sender = email_sender or get_email_sender()
        self._log = structlog.get_logger()

    def deliver_pending(self) -> int:
        with privileged_session_scope() as session:
            events = pending_alert_events(session)
            channels: dict[str, INotificationChannel] = {
                "in_app": InAppChannel(session),
                "email": EmailChannel(self._email_sender),
            }
            delivered = 0
            for ev in events:
                channel = channels.get(ev["channel"])
                target = DeliveryTarget(
                    tenant_id=ev["tenant_id"],
                    user_id=ev["user_id"],
                    email=ev["email"],
                    payload=ev["payload"],
                )
                try:
                    if channel is None:
                        raise ValueError(f"unknown channel {ev['channel']!r}")
                    with session.begin_nested():  # savepoint → isolate a failed delivery
                        channel.deliver(target)
                        mark_alert_event(session, ev["id"], "delivered")
                    delivered += 1
                except Exception as exc:
                    self._log.warning(
                        "notification_delivery_failed",
                        event_id=str(ev["id"]),
                        channel=ev["channel"],
                        error=str(exc),
                    )
                    mark_alert_event(session, ev["id"], "failed")

        self._log.info("notifications_delivered", delivered=delivered, total=len(events))
        return delivered

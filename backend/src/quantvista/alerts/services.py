"""Alert evaluation (QV-048) — cross-tenant, deduplicated, PIT-free (fires on current state).

Runs as a background job on the **privileged (RLS-bypassing) session**: reads every tenant's active
rules, evaluates each against the target stock's latest score/fundamentals snapshot, and writes an
``alert_events`` row when the condition holds — at most one per ``(rule, cycle date)`` via the 0010
dedup unique. Returns the number of NEW events; the caller (the job) emits ``AlertsFired``.
"""

from __future__ import annotations

from datetime import date

import structlog

from quantvista.alerts.evaluation import matches
from quantvista.alerts.repositories import (
    active_alert_rules,
    insert_alert_event,
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

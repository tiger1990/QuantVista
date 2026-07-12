"""Alert-rule persistence (QV-047). All reads/writes run on the RLS tenant session, so the
``app_current_tenant()`` policy scopes them automatically — no manual tenant filtering (mirrors
``analytics.saved_screens``). ``alert_events`` is written by QV-048, not here."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# The metrics an alert may test (QV-047 allow-list) → the columns that back them.
_METRIC_COLUMNS = (
    "composite_score",
    "fundamental_score",
    "momentum_score",
    "quality_score",
    "sentiment_score",
    "risk_score",
    "coverage",
    "pe",
    "pb",
    "roe",
    "roce",
    "debt_equity",
)


def _row(r: Any) -> dict[str, object]:
    return {
        "id": str(r["id"]),
        "scope": r["scope"],
        "target_id": str(r["target_id"]),
        "condition": r["condition"],  # jsonb → dict
        "channel": r["channel"],
        "is_active": r["is_active"],
        "created_at": r["created_at"].isoformat(),
    }


def create_alert_rule(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    scope: str,
    target_id: UUID,
    condition: dict[str, object],
    channel: str,
) -> dict[str, object]:
    """Insert an alert rule for the current tenant (RLS-scoped)."""
    row = (
        session.execute(
            text(
                "INSERT INTO alert_rules "
                "(tenant_id, user_id, scope, target_id, condition, channel) "
                "VALUES (:t, :u, :sc, :tg, CAST(:c AS jsonb), :ch) "
                "RETURNING id, scope, target_id, condition, channel, is_active, created_at"
            ),
            {
                "t": tenant_id,
                "u": user_id,
                "sc": scope,
                "tg": target_id,
                "c": json.dumps(condition),
                "ch": channel,
            },
        )
        .mappings()
        .one()
    )
    return _row(row)


def list_alert_rules(session: Session) -> list[dict[str, object]]:
    rows = (
        session.execute(
            text(
                "SELECT id, scope, target_id, condition, channel, is_active, created_at "
                "FROM alert_rules ORDER BY created_at DESC"
            )
        )
        .mappings()
        .all()
    )
    return [_row(r) for r in rows]


def count_active_alert_rules(session: Session) -> int:
    """Active rules for the current tenant (RLS-scoped) — the tier-limit denominator."""
    count: int = session.execute(
        text("SELECT count(*) FROM alert_rules WHERE is_active")
    ).scalar_one()
    return count


def delete_alert_rule(session: Session, rule_id: UUID) -> bool:
    """Delete a rule by id (RLS-scoped); ``False`` if it doesn't belong to the tenant."""
    row = session.execute(
        text("DELETE FROM alert_rules WHERE id = :id RETURNING id"), {"id": rule_id}
    ).first()
    return row is not None


# --- evaluation (QV-048): runs on the PRIVILEGED (RLS-bypassing) session, all tenants ---------
def active_alert_rules(session: Session) -> list[dict[str, Any]]:
    """Every tenant's active rules — for the cross-tenant evaluator (privileged session only)."""
    rows = (
        session.execute(
            text(
                "SELECT id, tenant_id, scope, target_id, condition FROM alert_rules WHERE is_active"
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "id": r["id"],
            "tenant_id": r["tenant_id"],
            "scope": r["scope"],
            "target_id": r["target_id"],
            "condition": r["condition"],
        }
        for r in rows
    ]


_METRICS_SQL = text(
    """
    SELECT s.id AS stock_id,
        sc.composite_score, sc.fundamental_score, sc.momentum_score, sc.quality_score,
        sc.sentiment_score, sc.risk_score, sc.coverage,
        f.pe, f.pb, f.roe, f.roce, f.debt_equity
    FROM stocks s
    LEFT JOIN LATERAL (
        SELECT * FROM scores WHERE stock_id = s.id ORDER BY date DESC LIMIT 1
    ) sc ON true
    LEFT JOIN LATERAL (
        SELECT pe, pb, roe, roce, debt_equity FROM fundamentals
        WHERE stock_id = s.id AND knowledge_to IS NULL ORDER BY period_end DESC LIMIT 1
    ) f ON true
    WHERE s.id = ANY(:ids)
    """  # noqa: S608 - static column list, ids parametrised
)


def stock_metrics(
    session: Session, stock_ids: Sequence[UUID]
) -> dict[UUID, dict[str, float | None]]:
    """Latest score + fundamentals metrics per stock (QV-047 alert metrics), keyed by stock_id."""
    if not stock_ids:
        return {}
    rows = session.execute(_METRICS_SQL, {"ids": list(stock_ids)}).mappings().all()
    return {
        r["stock_id"]: {m: (float(r[m]) if r[m] is not None else None) for m in _METRIC_COLUMNS}
        for r in rows
    }


_INSERT_EVENT_SQL = text(
    """
    INSERT INTO alert_events (tenant_id, alert_rule_id, dedup_key, payload)
    VALUES (:t, :r, :dk, CAST(:p AS jsonb))
    ON CONFLICT (alert_rule_id, dedup_key) DO NOTHING
    RETURNING id
    """
)


def insert_alert_event(
    session: Session,
    *,
    tenant_id: UUID,
    alert_rule_id: UUID,
    dedup_key: str,
    payload: dict[str, Any],
) -> bool:
    """Insert a fired event; ``False`` if one already exists for this (rule, cycle) — the dedup."""
    row = session.execute(
        _INSERT_EVENT_SQL,
        {"t": tenant_id, "r": alert_rule_id, "dk": dedup_key, "p": json.dumps(payload)},
    ).first()
    return row is not None


# --- delivery (QV-049): undelivered events joined to their rule's channel + the user's email -----
_PENDING_EVENTS_SQL = text(
    """
    SELECT e.id, e.tenant_id, r.user_id, r.channel, u.email, e.payload
    FROM alert_events e
    JOIN alert_rules r ON r.id = e.alert_rule_id
    JOIN users u ON u.id = r.user_id
    WHERE e.status IN ('pending','failed')
    ORDER BY e.fired_at
    """
)


def pending_alert_events(session: Session) -> list[dict[str, Any]]:
    """Undelivered/failed events + their delivery target (privileged; failed rows get retried)."""
    rows = session.execute(_PENDING_EVENTS_SQL).mappings().all()
    return [
        {
            "id": r["id"],
            "tenant_id": r["tenant_id"],
            "user_id": r["user_id"],
            "channel": r["channel"],
            "email": r["email"],
            "payload": r["payload"],
        }
        for r in rows
    ]


def mark_alert_event(session: Session, event_id: UUID, status: str) -> None:
    """Record a delivery outcome; ``delivered_at`` is set only when actually delivered."""
    session.execute(
        text(
            "UPDATE alert_events SET status = :s, "
            "delivered_at = CASE WHEN :s = 'delivered' THEN now() ELSE delivered_at END "
            "WHERE id = :id"
        ),
        {"s": status, "id": event_id},
    )


def insert_notification(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    type: str,
    payload: dict[str, Any],
) -> None:
    """Persist an in-app notification (0010) for the user (privileged session sets tenant_id)."""
    session.execute(
        text(
            "INSERT INTO notifications (tenant_id, user_id, type, payload) "
            "VALUES (:t, :u, :ty, CAST(:p AS jsonb))"
        ),
        {"t": tenant_id, "u": user_id, "ty": type, "p": json.dumps(payload)},
    )

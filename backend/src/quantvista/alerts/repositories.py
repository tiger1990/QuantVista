"""Alert-rule persistence (QV-047). All reads/writes run on the RLS tenant session, so the
``app_current_tenant()`` policy scopes them automatically — no manual tenant filtering (mirrors
``analytics.saved_screens``). ``alert_events`` is written by QV-048, not here."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


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

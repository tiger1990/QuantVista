"""Saved-screen persistence (QV-039). All reads/writes run on the RLS tenant session, so the
``app_current_tenant()`` policy scopes them automatically — no manual tenant filtering needed."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def _row(r: Any) -> dict[str, object]:
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "criteria": r["criteria"],  # jsonb → dict
        "created_at": r["created_at"].isoformat(),
    }


def create_saved_screen(
    session: Session, *, tenant_id: UUID, user_id: UUID, name: str, criteria: dict[str, object]
) -> dict[str, object]:
    """Insert a screen for the current tenant; raises ``IntegrityError`` on a duplicate name."""
    row = (
        session.execute(
            text(
                "INSERT INTO saved_screens (tenant_id, user_id, name, criteria) "
                "VALUES (:t, :u, :n, CAST(:c AS jsonb)) "
                "RETURNING id, name, criteria, created_at"
            ),
            {"t": tenant_id, "u": user_id, "n": name, "c": json.dumps(criteria)},
        )
        .mappings()
        .one()
    )
    return _row(row)


def list_saved_screens(session: Session) -> list[dict[str, object]]:
    rows = (
        session.execute(
            text(
                "SELECT id, name, criteria, created_at FROM saved_screens ORDER BY created_at DESC"
            )
        )
        .mappings()
        .all()
    )
    return [_row(r) for r in rows]


def count_saved_screens(session: Session) -> int:
    count: int = session.execute(text("SELECT count(*) FROM saved_screens")).scalar_one()
    return count


def delete_saved_screen(session: Session, screen_id: UUID) -> bool:
    """Delete a screen by id (RLS-scoped); ``False`` if it doesn't belong to the tenant."""
    row = session.execute(
        text("DELETE FROM saved_screens WHERE id = :id RETURNING id"), {"id": screen_id}
    ).first()
    return row is not None

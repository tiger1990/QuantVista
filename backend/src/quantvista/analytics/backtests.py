"""Backtest persistence (QV-062).

CRUD (``create``/``get``/``list``) runs on the **RLS tenant session** — the ``backtests_isolation``
policy scopes rows to ``app_current_tenant()`` automatically. The status transitions
(``mark_running``/``mark_succeeded``/``mark_failed``) are called by the **background job** on a
privileged (RLS-bypassing) session, keyed by ``id`` — see ``jobs/backtest.py``. The engine itself
is QV-065; this module only moves the row through its lifecycle.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _row(r: Any) -> dict[str, object]:
    return {
        "id": str(r["id"]),
        "status": r["status"],
        "spec": r["spec"],  # jsonb → dict
        "metrics": r["metrics"],  # jsonb → dict | None
        "result_ref": r["result_ref"],
        "error": r["error"],
        "created_at": r["created_at"].isoformat(),
        "started_at": _iso(r["started_at"]),
        "finished_at": _iso(r["finished_at"]),
    }


def create_backtest(
    session: Session, *, tenant_id: UUID, user_id: UUID, spec: dict[str, object]
) -> dict[str, object]:
    """Insert a queued backtest for the current tenant; returns the row."""
    row = (
        session.execute(
            text(
                "INSERT INTO backtests (tenant_id, user_id, spec, status) "
                "VALUES (:t, :u, CAST(:s AS jsonb), 'queued') "
                "RETURNING id, status, spec, metrics, result_ref, error, "
                "created_at, started_at, finished_at"
            ),
            {"t": tenant_id, "u": user_id, "s": json.dumps(spec)},
        )
        .mappings()
        .one()
    )
    return _row(row)


def get_backtest(session: Session, backtest_id: UUID) -> dict[str, object] | None:
    row = (
        session.execute(
            text(
                "SELECT id, status, spec, metrics, result_ref, error, "
                "created_at, started_at, finished_at FROM backtests WHERE id = :id"
            ),
            {"id": backtest_id},
        )
        .mappings()
        .one_or_none()
    )
    return _row(row) if row is not None else None


def list_backtests(session: Session) -> list[dict[str, object]]:
    """The current tenant's backtests, newest first (RLS-scoped)."""
    rows = (
        session.execute(
            text(
                "SELECT id, status, spec, metrics, result_ref, error, "
                "created_at, started_at, finished_at FROM backtests ORDER BY created_at DESC"
            )
        )
        .mappings()
        .all()
    )
    return [_row(r) for r in rows]


def mark_running(session: Session, backtest_id: UUID) -> bool:
    """queued → running (+ started_at). Returns True if this call made the transition (idempotent
    guard against Celery at-least-once re-delivery). ``RETURNING`` keeps it typed (no rowcount)."""
    row = session.execute(
        text(
            "UPDATE backtests SET status = 'running', started_at = now() "
            "WHERE id = :id AND status = 'queued' RETURNING id"
        ),
        {"id": backtest_id},
    ).one_or_none()
    return row is not None


def mark_succeeded(
    session: Session,
    backtest_id: UUID,
    *,
    metrics: dict[str, object],
    result_ref: str | None,
    model_version: str | None = None,
    weights_version: str | None = None,
) -> None:
    session.execute(
        text(
            "UPDATE backtests SET status = 'succeeded', finished_at = now(), "
            "metrics = CAST(:m AS jsonb), result_ref = :r, "
            "model_version = :mv, weights_version = :wv WHERE id = :id"
        ),
        {
            "id": backtest_id,
            "m": json.dumps(metrics),
            "r": result_ref,
            "mv": model_version,
            "wv": weights_version,
        },
    )


def mark_failed(session: Session, backtest_id: UUID, *, error: str) -> None:
    session.execute(
        text(
            "UPDATE backtests SET status = 'failed', finished_at = now(), error = :e WHERE id = :id"
        ),
        {"id": backtest_id, "e": error[:2000]},
    )


__all__ = [
    "create_backtest",
    "get_backtest",
    "list_backtests",
    "mark_failed",
    "mark_running",
    "mark_succeeded",
]

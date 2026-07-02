"""jobs_runs ledger (QV-015): idempotent run records for background jobs.

Writes the run lifecycle to the global ``jobs_runs`` table via the **privileged** engine
(jobs_runs has no tenant_id / no RLS). The idempotency guarantee rides on the table's
``UNIQUE (job_name, run_key)`` constraint: ``start`` inserts a ``running`` row, and on a key
collision it re-runs a previously failed/running key but **skips** one that already succeeded
(returns ``None``). ``06`` §1.1.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from quantvista.core.db import privileged_session_scope

# Insert a fresh run; on (job_name, run_key) conflict, reclaim the row for a re-run UNLESS it
# already succeeded (the WHERE then matches no row → RETURNING is empty → caller skips).
_START_SQL = text(
    """
    INSERT INTO jobs_runs (job_name, run_key, status, metadata)
    VALUES (:job, :key, 'running', CAST(:meta AS jsonb))
    ON CONFLICT (job_name, run_key) DO UPDATE
        SET status = 'running', started_at = now(), finished_at = NULL, error = NULL,
            rows_in = NULL, rows_out = NULL, metadata = EXCLUDED.metadata
        WHERE jobs_runs.status <> 'succeeded'
    RETURNING id
    """
)

_SUCCEED_SQL = text(
    "UPDATE jobs_runs SET status = 'succeeded', finished_at = now(), "
    "rows_in = :rows_in, rows_out = :rows_out WHERE id = :id"
)

_FAIL_SQL = text(
    "UPDATE jobs_runs SET status = 'failed', finished_at = now(), error = :error WHERE id = :id"
)


class JobRunLedger:
    """Records job runs in ``jobs_runs`` (global table, admin-written)."""

    def start(self, job_name: str, key: str, metadata: dict[str, Any] | None = None) -> int | None:
        """Begin a run; return its id, or ``None`` if this key already succeeded (skip)."""
        with privileged_session_scope() as session:
            row = session.execute(
                _START_SQL,
                {"job": job_name, "key": key, "meta": json.dumps(metadata or {})},
            ).one_or_none()
        return int(row[0]) if row is not None else None

    def succeed(self, run_id: int, rows_in: int | None, rows_out: int | None) -> None:
        with privileged_session_scope() as session:
            session.execute(_SUCCEED_SQL, {"id": run_id, "rows_in": rows_in, "rows_out": rows_out})

    def fail(self, run_id: int, error: str) -> None:
        with privileged_session_scope() as session:
            session.execute(_FAIL_SQL, {"id": run_id, "error": error})

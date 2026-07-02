"""jobs_runs schema guarantees (QV-015) — verifies migration ``0012``.

The ``jobs_runs`` DDL was authored in ``0012_platform.py``; these tests pin the idempotency
constraint (``UNIQUE (job_name, run_key)``), the status CHECK, the ``metadata`` default, and
the global/no-RLS posture. Admin role; all writes rolled back (no residue).
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


@pytest.fixture
def conn(admin_engine: Engine) -> Iterator[Connection]:
    with admin_engine.connect() as connection:
        trans = connection.begin()
        try:
            yield connection
        finally:
            trans.rollback()


def _insert(conn: Connection, job: str, key: str, status: str = "running") -> None:
    conn.execute(
        text("INSERT INTO jobs_runs (job_name, run_key, status) VALUES (:j, :k, :s)"),
        {"j": job, "k": key, "s": status},
    )


def test_unique_job_name_run_key(conn: Connection) -> None:
    # Arrange
    job, key = f"t{uuid4().hex[:8]}", "prices:NSE:2026-06-13"
    _insert(conn, job, key)
    # Act / Assert — the idempotency key rejects a duplicate
    with pytest.raises(IntegrityError), conn.begin_nested():
        _insert(conn, job, key)


def test_status_check_rejects_unknown(conn: Connection) -> None:
    # Act / Assert
    with pytest.raises(IntegrityError), conn.begin_nested():
        _insert(conn, f"t{uuid4().hex[:8]}", "k", status="bogus")


def test_metadata_defaults_to_empty_jsonb(conn: Connection) -> None:
    # Arrange / Act
    job = f"t{uuid4().hex[:8]}"
    _insert(conn, job, "k")
    meta = conn.execute(
        text("SELECT metadata FROM jobs_runs WHERE job_name = :j"), {"j": job}
    ).scalar_one()
    # Assert
    assert meta == {}


def test_jobs_runs_is_global_no_rls(conn: Connection) -> None:
    tenant_cols = conn.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'jobs_runs' AND column_name = 'tenant_id'"
        )
    ).scalar_one()
    rls = conn.execute(
        text("SELECT relrowsecurity FROM pg_class WHERE relname = 'jobs_runs'")
    ).scalar_one()
    policies = conn.execute(
        text("SELECT count(*) FROM pg_policies WHERE tablename = 'jobs_runs'")
    ).scalar_one()
    assert tenant_cols == 0
    assert rls is False
    assert policies == 0

"""Job framework idempotency + lifecycle against real Postgres (QV-015).

Exercises ``JobRunLedger`` + ``run_job`` end-to-end (the ledger commits its own transactions,
so each test uses a unique ``job_name`` and deletes its ``jobs_runs`` rows afterwards).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs.framework import JobResult, JobStatus, run_job
from quantvista.jobs.ledger import JobRunLedger

pytestmark = pytest.mark.integration


@pytest.fixture
def job_name(admin_engine: Engine) -> Iterator[str]:
    name = f"test_{uuid4().hex}"
    yield name
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs_runs WHERE job_name = :j"), {"j": name})


def _row(admin_engine: Engine, job_name: str, key: str) -> tuple[Any, ...]:
    with admin_engine.connect() as conn:
        return tuple(
            conn.execute(
                text(
                    "SELECT status, rows_in, rows_out, error FROM jobs_runs "
                    "WHERE job_name = :j AND run_key = :k"
                ),
                {"j": job_name, "k": key},
            ).one()
        )


def test_first_run_records_succeeded(admin_engine: Engine, job_name: str) -> None:
    # Act
    outcome = run_job(job_name, "k1", lambda: JobResult(10, 8), ledger=JobRunLedger())
    # Assert
    assert outcome.status is JobStatus.SUCCEEDED
    status, rows_in, rows_out, error = _row(admin_engine, job_name, "k1")
    assert status == "succeeded"
    assert (rows_in, rows_out, error) == (10, 8, None)


def test_second_run_same_key_is_skipped(admin_engine: Engine, job_name: str) -> None:
    # Arrange — first run succeeds
    calls = {"n": 0}

    def work() -> JobResult:
        calls["n"] += 1
        return JobResult(1, 1)

    run_job(job_name, "k", work, ledger=JobRunLedger())
    # Act — a second run with the same key must skip (idempotent)
    outcome = run_job(job_name, "k", work, ledger=JobRunLedger())
    # Assert — work ran exactly once; the row stays succeeded
    assert outcome.status is JobStatus.SKIPPED
    assert calls["n"] == 1
    assert _row(admin_engine, job_name, "k")[0] == "succeeded"


def test_failing_work_records_failed_and_reraises(admin_engine: Engine, job_name: str) -> None:
    # Act / Assert
    with pytest.raises(RuntimeError, match="kaboom"):

        def work() -> JobResult:
            raise RuntimeError("kaboom")

        run_job(job_name, "k", work, ledger=JobRunLedger())
    status, _, _, error = _row(admin_engine, job_name, "k")
    assert status == "failed"
    assert error == "kaboom"


def test_rerun_after_failure_is_allowed(admin_engine: Engine, job_name: str) -> None:
    # Arrange — a failed run
    with pytest.raises(RuntimeError):
        run_job(
            job_name, "k", lambda: (_ for _ in ()).throw(RuntimeError("x")), ledger=JobRunLedger()
        )
    # Act — re-running the same key after failure is allowed and can succeed
    outcome = run_job(job_name, "k", lambda: JobResult(2, 2), ledger=JobRunLedger())
    # Assert
    assert outcome.status is JobStatus.SUCCEEDED
    assert _row(admin_engine, job_name, "k")[0] == "succeeded"

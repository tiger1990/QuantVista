"""The Beat sample task runs end-to-end through the ledger (QV-015), eager (no broker).

Uses Celery's ``.apply()`` to execute the task locally/synchronously — no Redis/worker needed
(that live path is deferred to PV-004). The ledger commits real ``jobs_runs`` rows, so the
test cleans up its unique run_key afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs.celery_app import SAMPLE_JOB_NAME, sample_scheduled_job

pytestmark = pytest.mark.integration


@pytest.fixture
def run_key_value(admin_engine: Engine) -> Iterator[str]:
    key = f"sample:test:{uuid4().hex}"
    yield key
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM jobs_runs WHERE job_name = :j AND run_key = :k"),
            {"j": SAMPLE_JOB_NAME, "k": key},
        )


def _status(admin_engine: Engine, key: str) -> str:
    with admin_engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT status FROM jobs_runs WHERE job_name = :j AND run_key = :k"),
                {"j": SAMPLE_JOB_NAME, "k": key},
            ).scalar_one()
        )


def test_sample_job_runs_and_records(admin_engine: Engine, run_key_value: str) -> None:
    # Act — run the task eagerly with an explicit key
    result = sample_scheduled_job.apply(args=[run_key_value])
    # Assert — succeeded and recorded in jobs_runs
    assert result.get() == "succeeded"
    assert _status(admin_engine, run_key_value) == "succeeded"


def test_sample_job_rerun_is_idempotent(admin_engine: Engine, run_key_value: str) -> None:
    # Arrange
    sample_scheduled_job.apply(args=[run_key_value])
    # Act — second run with the same key skips
    result = sample_scheduled_job.apply(args=[run_key_value])
    # Assert
    assert result.get() == "skipped"
    assert _status(admin_engine, run_key_value) == "succeeded"

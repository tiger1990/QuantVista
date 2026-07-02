"""Unit tests for the job framework lifecycle (no DB — fake ledger)."""

from __future__ import annotations

from typing import Any

import pytest

from quantvista.jobs.framework import JobResult, JobStatus, run_job, run_key


class _FakeLedger:
    def __init__(self, start_returns: int | None) -> None:
        self._start_returns = start_returns
        self.calls: list[tuple[Any, ...]] = []

    def start(self, job_name: str, key: str, metadata: dict[str, Any] | None) -> int | None:
        self.calls.append(("start", job_name, key))
        return self._start_returns

    def succeed(self, run_id: int, rows_in: int | None, rows_out: int | None) -> None:
        self.calls.append(("succeed", run_id, rows_in, rows_out))

    def fail(self, run_id: int, error: str) -> None:
        self.calls.append(("fail", run_id, error))


def test_run_key_joins_parts() -> None:
    assert run_key("prices", "NSE", "2026-06-13") == "prices:NSE:2026-06-13"


def test_run_job_records_success() -> None:
    # Arrange
    ledger = _FakeLedger(start_returns=5)
    # Act
    outcome = run_job("ingest", "prices:NSE:2026-06-13", lambda: JobResult(3, 2), ledger=ledger)
    # Assert
    assert outcome.status is JobStatus.SUCCEEDED
    assert outcome.run_id == 5
    assert ("succeed", 5, 3, 2) in ledger.calls


def test_run_job_skips_when_start_returns_none() -> None:
    # Arrange — start() returns None → key already succeeded
    ledger = _FakeLedger(start_returns=None)

    def _work() -> JobResult:
        raise AssertionError("work must NOT run when the run is skipped")

    # Act
    outcome = run_job("ingest", "k", _work, ledger=ledger)
    # Assert
    assert outcome.status is JobStatus.SKIPPED
    assert not any(c[0] in ("succeed", "fail") for c in ledger.calls)


def test_run_job_records_failure_and_reraises() -> None:
    # Arrange
    ledger = _FakeLedger(start_returns=7)

    def _work() -> JobResult:
        raise ValueError("boom")

    # Act / Assert
    with pytest.raises(ValueError, match="boom"):
        run_job("ingest", "k", _work, ledger=ledger)
    assert ("fail", 7, "boom") in ledger.calls

"""Reusable job framework (QV-015): run keys, result/outcome types, lifecycle wrapper.

Every background job computes a deterministic ``run_key`` and runs through ``run_job``, which
records its lifecycle to ``jobs_runs`` via the ledger (idempotent — a re-run of an already
succeeded key is skipped) and emits structured logs (job_name/run_key/status/duration/rows).
This is the skeleton the ingestion jobs (QV-016+) are built on. ``06`` §1.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import structlog

from quantvista.jobs.ledger import JobRunLedger


def run_key(*parts: str) -> str:
    """Join parts into an idempotency key, e.g. ``run_key('prices','NSE','2026-06-13')``."""
    return ":".join(parts)


@dataclass(frozen=True, slots=True)
class JobResult:
    """What a job's work function reports back (both counts optional)."""

    rows_in: int | None = None
    rows_out: int | None = None


class JobStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """The result of a ``run_job`` call."""

    status: JobStatus
    run_id: int | None
    rows_in: int | None = None
    rows_out: int | None = None
    duration_s: float = 0.0


# A job's unit of work: takes no args, returns a JobResult (or None).
WorkFn = Callable[[], "JobResult | None"]


class _Ledger(Protocol):
    def start(self, job_name: str, key: str, metadata: dict[str, Any] | None) -> int | None: ...
    def succeed(self, run_id: int, rows_in: int | None, rows_out: int | None) -> None: ...
    def fail(self, run_id: int, error: str) -> None: ...


def run_job(
    job_name: str,
    key: str,
    work: WorkFn,
    *,
    ledger: _Ledger | None = None,
    metadata: dict[str, Any] | None = None,
) -> JobOutcome:
    """Run ``work`` under the ledger lifecycle: skip if already succeeded, else record."""
    ledger = ledger or JobRunLedger()
    log = structlog.get_logger().bind(job_name=job_name, run_key=key)

    run_id = ledger.start(job_name, key, metadata)
    if run_id is None:
        log.info("job_skipped")
        return JobOutcome(status=JobStatus.SKIPPED, run_id=None)

    start = time.perf_counter()
    try:
        result = work() or JobResult()
    except Exception as exc:
        ledger.fail(run_id, str(exc))
        log.error("job_failed", error=str(exc), duration_s=round(time.perf_counter() - start, 4))
        raise

    duration = time.perf_counter() - start
    ledger.succeed(run_id, result.rows_in, result.rows_out)
    log.info(
        "job_succeeded",
        rows_in=result.rows_in,
        rows_out=result.rows_out,
        duration_s=round(duration, 4),
    )
    return JobOutcome(
        status=JobStatus.SUCCEEDED,
        run_id=run_id,
        rows_in=result.rows_in,
        rows_out=result.rows_out,
        duration_s=duration,
    )

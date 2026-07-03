---
baseline_commit: b629e6d6e7bc699a25ee7638a07b35830d9e58a3
---

# Story 3.4: QV-015 — Job framework: idempotency + jobs_runs + Celery/Beat wiring

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **an operator**,
I want **every background job to compute a deterministic `run_key`, record start/finish/rows/status/error in `jobs_runs`, and be safe to re-run — plus Celery Beat configured with a sample scheduled task**,
so that **retries are safe (idempotent), every run is auditable, and the pipeline has a proven job skeleton to build ingestion on**.

> Canonical ID **QV-015** · Epic 3 (EPIC-DATA) · `[BE]` · 5pts · Sprint 01 · depends: **QV-002** (done)
> Authoritative spec: `plans/06-scheduler-and-jobs.md` §1 (principles) + §2 (job catalog / run-key shapes). `jobs_runs` schema: `plans/03` §4 + migration `0012`. Integrates QV-009 structured logging.

## ⚠️ Read this first — hybrid scope + the environment boundary

This is a **hybrid**: the `jobs_runs` **table already exists** (verify it), but the **job framework is real new code** (build it). Redis is **not** reachable in this environment, so the live worker+Beat+Redis run is deferred.

- **`jobs_runs` table already exists** in migration **`0012_platform.py`** (`id, job_name, run_key, status CHECK(running/succeeded/failed/skipped), started_at, finished_at, rows_in, rows_out, error, metadata jsonb, UNIQUE (job_name, run_key)`). **DO NOT write a new migration for it** — verify it with a test.
- **Build the framework code** (new): a `run_key` builder, a **`JobRunLedger`** that writes the run lifecycle to `jobs_runs` with **idempotent start** (the `UNIQUE (job_name, run_key)` constraint), a **`run_job`/`execute_job`** wrapper (start → work → succeed/fail, structured logs), and **Celery/Beat wiring** (retry defaults + a `beat_schedule` with one **sample scheduled task** wired end-to-end through the ledger).
- **Environment boundary:** Redis is down here (`redis://localhost:6379` refused), so a **live** Beat→Redis→worker run cannot be verified. All framework logic is tested **without a broker** using Celery **eager mode** (`task_always_eager`) + the reachable local Postgres. The live end-to-end (Beat fires the sample task over Redis, a worker consumes it, a `jobs_runs` row lands) is recorded as **PV-004** (mirrors PV-001).

## Acceptance Criteria

1. **`run_key` builder.** A pure helper `run_key(*parts) -> str` joins parts with `:` (e.g. `run_key("prices", "NSE", "2026-06-13") == "prices:NSE:2026-06-13"`), matching the `06` §2 key shapes. Deterministic, no side effects.
2. **`JobRunLedger` — idempotent start (`06` §1.1).** Writes to `jobs_runs` via the **privileged** (global-table) engine. `start(job_name, run_key, metadata) -> int | None`: inserts a `running` row; **on `(job_name, run_key)` conflict**, if the existing run already **succeeded** it returns `None` (caller skips), otherwise (previously `failed`/`running`) it resets the row to `running` and returns its id (safe retry). `succeed(run_id, rows_in, rows_out)` and `fail(run_id, error)` update status + `finished_at` (+ rows / error). This is the at-least-once safety net.
3. **`run_job` lifecycle wrapper.** `run_job(job_name, run_key, work, *, ledger, metadata=None) -> JobOutcome` calls `ledger.start`; **skips** (no work) when start returns `None`; otherwise runs `work()`, then `ledger.succeed(...)` on success or `ledger.fail(...)` + re-raise on exception. Emits **structured logs** (QV-009 structlog) bound with `job_name`/`run_key` and, per run, `status`/`duration_s`/`rows_in`/`rows_out` (project rule: structured logs per run). `work()` returns a small `JobResult(rows_in, rows_out)` (both optional).
4. **`jobs_runs` schema verified — integration test.** Assert the table exists with the `UNIQUE (job_name, run_key)`, the `status` CHECK (rejects an unknown status), `metadata` default `{}`, and that it is **global** (no `tenant_id`, `relrowsecurity=false`, no policies). **No new migration.**
5. **Idempotency + lifecycle — integration tests (real Postgres).** A first `run_job` for a fresh key records a `succeeded` row (with rows); a **second** `run_job` with the **same key skips** (status stays `succeeded`, `work` not re-invoked); a `work()` that raises records `failed` (+ `error`) and re-raises; a **re-run after failure** is allowed (starts `running` again). Tests use unique `job_name`s and clean up their `jobs_runs` rows.
6. **Celery/Beat wiring + sample task.** `create_celery()` sets **retry defaults** aligned to `06` §1.4 (`acks_late`, `task_default_retry_delay`/backoff+jitter conventions) and a **`beat_schedule`** containing one **sample scheduled task** (e.g. `quantvista.sample_scheduled_job`) that runs end-to-end through `run_job` + the ledger. A test using **eager mode** (`task_always_eager=True`) invokes the sample task and asserts a `jobs_runs` row is written and re-running skips. A unit test asserts the `beat_schedule` entry + retry config exist. **Do not break** the existing `ping` task or `-A quantvista.jobs.celery_app` discovery or the QV-009 `worker_process_init` observability wiring.
7. **Live run deferred (PV-004).** Add a `PV-004` row to `docs/pending-verifications.md`: **what** (start Redis + a Celery worker + Beat; confirm the sample task fires on schedule and a `jobs_runs` row is recorded end-to-end), **why** (no Redis in this environment), **how** (runbook: `redis-server`/compose, `celery -A quantvista.jobs.celery_app worker`, `celery -A ... beat`, observe), **gate** (before QV-016 ingestion relies on Beat-scheduled jobs in a live env; tied to PV-001 container stack).
8. **Gates green:** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` (jobs is a composition root — may import core; core/schemas stay pure) + `pytest` (unit + integration) all green locally and in CI. Integration tests skip cleanly without Postgres; eager Celery tests need no broker.

## Tasks / Subtasks

- [x] **Task 1 — run_key + result/outcome types** (AC: #1, #3)
  - [x] `jobs/framework.py`: `run_key(*parts)`; frozen `JobResult(rows_in: int|None, rows_out: int|None)`; `JobOutcome(status, run_id|None, rows_in, rows_out, duration_s)`. Unit-test `run_key`.
- [x] **Task 2 — JobRunLedger** (AC: #2)
  - [x] `jobs/ledger.py`: `JobRunLedger` using `core.db.privileged_session_scope()` (global table). `start` via `INSERT ... ON CONFLICT (job_name, run_key) DO UPDATE ... WHERE status <> 'succeeded' RETURNING id` (returns `None` when the existing row already succeeded). `succeed`/`fail` updates. Optional `IJobRunLedger` Protocol in `core/interfaces.py`.
- [x] **Task 3 — run_job wrapper** (AC: #3)
  - [x] `jobs/framework.py`: `run_job(...)` lifecycle + structlog (bind job_name/run_key; log skipped/succeeded/failed with duration + rows). Skip path when `start()` → `None`.
- [x] **Task 4 — jobs_runs schema verify test** (AC: #4)
  - [x] `tests/integration/test_jobs_runs_schema.py` (`@pytest.mark.integration`, `admin_engine`, rollback pattern): UNIQUE `(job_name, run_key)`; status CHECK rejects unknown; `metadata` default `{}`; global/no-RLS.
- [x] **Task 5 — idempotency + lifecycle tests** (AC: #5)
  - [x] `tests/integration/test_job_framework.py`: fresh run → succeeded; same key → skipped (work not called); failing work → failed + raises; re-run after failure allowed. Unique job_name per test + cleanup.
- [x] **Task 6 — Celery/Beat wiring + sample task** (AC: #6)
  - [x] `jobs/celery_app.py`: retry defaults + `beat_schedule` with `sample_scheduled_job` (wired via `run_job` + `JobRunLedger`). Keep `ping`, discovery, and QV-009 `worker_process_init` intact.
  - [x] `tests/test_celery_app.py` (+ maybe an integration test): eager-mode invoke of the sample task writes a `jobs_runs` row + re-run skips; assert `beat_schedule`/retry config present.
- [x] **Task 7 — PV-004 + gates** (AC: #7, #8)
  - [x] Add **PV-004** to `docs/pending-verifications.md`. Run `ruff`/`ruff format`/`mypy`/`lint-imports`/`pytest`; record commands/output. Reconcile QV-014 → done (housekeeping, this branch).

## Dev Notes

### Scope discipline — build the framework, verify the table
QV-015 = the **reusable job skeleton** (run_key + ledger + `run_job` + Celery/Beat config + one sample task), fully tested offline. **Not this story:** the real ingestion jobs (`ingest_daily_prices` etc. → QV-016+), the **event-driven DAG** triggering between jobs (`IEventBus`/Redis Streams → QV-024 and later), a real dead-letter-queue infra (baseline sets retry/backoff/jitter; DLQ + alerting land with QV-082), per-stock partial-failure isolation (a `06` §1.4 property that the *ingestion* jobs implement on top of this skeleton). Don't write a new migration for `jobs_runs` (exists in `0012`).

### What already exists / context to build on
- **`jobs_runs`** (migration `0012_platform.py`, live): `id bigint IDENTITY PK`, `job_name`, `run_key`, `status` CHECK(`running`/`succeeded`/`failed`/`skipped`) default `running`, `started_at`, `finished_at`, `rows_in`, `rows_out`, `error`, `metadata jsonb DEFAULT '{}'`, **UNIQUE `(job_name, run_key)`**, indexes `(job_name, started_at DESC)` + `(status)`. Global/operational (no `tenant_id`, no RLS).
- **`jobs/celery_app.py`** (QV-002 + QV-009): `create_celery()` (Redis broker/result from `Settings.redis_url`, `task_default_queue='default'`, `timezone='UTC'`), `ping` task, module-level `app`/`celery_app` for `-A` discovery, `install_worker_metrics()` at create + `worker_process_init` → `configure_observability("worker")`. **Extend, don't break** these.
- **`core/db.py`**: `privileged_session_scope()` — transactional session on the **admin** engine for GLOBAL tables (jobs_runs is global). Use it in the ledger; do **not** use the tenant/app engine.
- **`core/interfaces.py`**: `IEventBus`, `IAuditLogger` Protocols — add `IJobRunLedger` here if you want the seam published (optional; the ledger can also just be a concrete class in `jobs`).
- **QV-009 observability**: `structlog.get_logger()` is configured for the worker role; `run_job` should emit JSON logs with `job_name`/`run_key`/`status`/`duration_s`/`rows_*` (PII redaction already applies).
- **`06` §2 run-key shapes:** `prices:{market}:{date}`, `master:{market}:{week}`, `constituents:{index}:{date}`, etc. — `run_key()` just joins; the *jobs* choose the parts (QV-016+).
- **Time rule (project-context):** schedules use **IST cadence** but timestamps stored/computed in **UTC** (`jobs_runs.*_at` are `timestamptz`; Celery `timezone='UTC'`). Beat `crontab` for the sample task can be any cadence — it's a placeholder.

### Testing notes
- **No Redis needed.** Use Celery **eager mode** for the sample-task test: set `app.conf.task_always_eager = True` (+ `task_eager_propagates = True`) in the test, call the task, assert the `jobs_runs` row. The ledger writes via its own committed transactions (real rows) — so tests must **clean up** using a unique `job_name` per test (e.g. `f"test_{uuid4().hex}"`) and `DELETE FROM jobs_runs WHERE job_name = ...` in teardown. (Unlike the QV-013/014 schema tests, the ledger commits, so a test-transaction rollback won't undo it.)
- Idempotent `start` under conflict: assert a second `start` for a **succeeded** key returns `None`; for a **failed** key returns an id (re-run). Use `SAVEPOINT` only where you assert a raw constraint violation directly.
- Schema-verify test mirrors `tests/integration/test_reference_schema.py` / `test_daily_prices_schema.py` (admin_engine, rollback, SAVEPOINT for the status-CHECK violation).
- Keep AAA + behavior-named. Coverage ≥80% for the new framework modules.

### Project Structure Notes
- **New:** `jobs/framework.py`, `jobs/ledger.py`; `tests/integration/test_jobs_runs_schema.py`, `tests/integration/test_job_framework.py` (+ additions to `tests/test_celery_app.py`).
- **Modified:** `jobs/celery_app.py` (beat_schedule + retry defaults + sample task), possibly `core/interfaces.py` (`IJobRunLedger`), `docs/pending-verifications.md` (PV-004).
- **Housekeeping on this branch:** `sprint-status.yaml` QV-014 → done.
- `jobs` is a composition root in the import-linter DAG (may import `core`); `core`/`schemas` stay pure. Keep files 200–400 lines.

### References
- [Source: plans/sprints/sprint-01-data-backbone-i.md#QV-015] — story + AC (run_key; write start/finish/rows/status/error to jobs_runs; Celery/Beat + sample scheduled task end-to-end).
- [Source: plans/06-scheduler-and-jobs.md#1-principles] — idempotent & keyed; DAG-not-cron; backfill = same code; fail-loud/retry-smart; correctness over speed.
- [Source: plans/06-scheduler-and-jobs.md#2-job-catalog] — run-key shapes + cadences (context for QV-016+).
- [Source: backend/src/quantvista/db/migrations/versions/0012_platform.py] — the `jobs_runs` DDL to verify.
- [Source: backend/src/quantvista/jobs/celery_app.py] — existing Celery app + QV-009 worker wiring to extend.
- [Source: backend/src/quantvista/core/db.py] — `privileged_session_scope()` for global-table writes.
- [Source: backend/src/quantvista/core/interfaces.py] — Protocol style for an optional `IJobRunLedger`.
- [Source: backend/tests/integration/test_daily_prices_schema.py] — integration test/admin_engine/rollback pattern to reuse.
- [Source: docs/pending-verifications.md] — PV-001 pattern for the PV-004 deferral (live broker/worker/Beat).
- [Source: _bmad-output/project-context.md] — Jobs rules (run_key, idempotent upserts, retries/backoff→DLQ, structured logs to jobs_runs, IST cadence/UTC storage); rule #3 (module boundaries); rule #6 (same image, three roles).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Redis **not** reachable here (`redis://localhost:6379` refused) → sample task tested via Celery
  `.apply()` (eager, no broker); local **PostgreSQL 18.4** reachable for the ledger.
- `pytest` (job framework + schema + celery): 16 new tests pass.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (86 files) ·
  `lint-imports` 3 kept/0 broken · full `pytest` → **147 passed** (16 new; prior 131 unaffected).
- Coverage: `jobs/framework.py` 100%, `jobs/ledger.py` 100%, `jobs/celery_app.py` 85% (uncovered =
  the QV-009 `worker_process_init` lines, which need a live worker — unchanged by this story). TOTAL 94%.

### Completion Notes List

- **Hybrid delivered:** verified the pre-existing `jobs_runs` table (`0012`) via an integration test,
  and **built the framework**: `run_key` + `JobResult`/`JobOutcome`/`JobStatus` (`jobs/framework.py`),
  `JobRunLedger` (`jobs/ledger.py`), the `run_job` lifecycle wrapper, and Celery Beat + retry wiring +
  a `sample_scheduled_job` (`jobs/celery_app.py`). **No new migration.**
- **Idempotency (06 §1.1)** rides on `UNIQUE (job_name, run_key)`: `start` does
  `INSERT ... ON CONFLICT DO UPDATE ... WHERE status <> 'succeeded' RETURNING id` — a fresh key or a
  previously failed/running key returns an id (run/retry), an already-succeeded key returns `None`
  (skip). Verified against real Postgres: fresh→succeeded, same key→skipped (work not re-invoked),
  failure→failed+reraise, re-run-after-failure→allowed.
- **`run_job`** emits QV-009 structlog (`job_name`/`run_key` bound; `job_succeeded`/`job_failed`/
  `job_skipped` with `duration_s` + rows) — the "structured logs per run" project rule.
- **Ledger uses `privileged_session_scope()`** (admin engine) — `jobs_runs` is a global/operational
  table (no `tenant_id`/RLS), so it is admin-written, not tenant-scoped. Parameterized SQL throughout.
- **Celery wiring** keeps `ping`, `-A` discovery, and the QV-009 `worker_process_init` observability
  intact; adds `task_acks_late`/`task_reject_on_worker_lost` + a `beat_schedule` (`sample-heartbeat`).
  The sample task runs the full ledger path; tested eagerly via `.apply()` (no broker).
- **`IJobRunLedger` in `core/interfaces.py` intentionally NOT added** — the story marked it optional;
  the `_Ledger` `Protocol` in `framework.py` already provides the seam (and enabled the DB-free unit
  tests with a fake ledger). No cross-context consumer needs the published interface yet.
- **No security-reviewer pass:** parameterized SQL, no auth/PII/user-input surface; `job_name`/`run_key`
  originate in job code, `metadata` is `json.dumps`'d into a `jsonb` bind param.
- **PV-004 native-broker run VERIFIED (2026-07-03), not deferred.** Redis is natively installable on
  this box (Homebrew, like Postgres) — it wasn't truly blocked, just not installed. `brew install redis`
  → ran a real `celery worker` against native Redis + Postgres → `sample_scheduled_job.delay()` was
  consumed → `jobs_runs` row `succeeded`; same-key re-run → `skipped` (idempotency over the real broker);
  `celery beat` started + loaded the `sample-heartbeat` schedule. **PV-004 closed (native)**; only the
  *containerized* variant remains under PV-001. (Lesson: check native install before deferring — see memory.)
- **Housekeeping bundled on this branch:** QV-014 reconciled `review → done`.

### File List

**New**
- `backend/src/quantvista/jobs/framework.py` — `run_key`, `JobResult`, `JobStatus`, `JobOutcome`, `run_job`.
- `backend/src/quantvista/jobs/ledger.py` — `JobRunLedger` (idempotent start + succeed/fail).
- `backend/tests/test_job_framework_unit.py` — DB-free lifecycle unit tests (fake ledger).
- `backend/tests/integration/test_jobs_runs_schema.py` — verifies the `0012` `jobs_runs` schema.
- `backend/tests/integration/test_job_framework.py` — ledger idempotency + lifecycle vs real Postgres.
- `backend/tests/integration/test_sample_scheduled_job.py` — sample task end-to-end via eager `.apply()`.

**Modified**
- `backend/src/quantvista/jobs/celery_app.py` — `beat_schedule`, retry defaults, `sample_scheduled_job`.
- `backend/tests/test_celery_app.py` — beat/retry config + sample-task-registered assertions.
- `docs/pending-verifications.md` — **PV-004** (live worker/Beat/Redis run, tied to PV-001).

**Housekeeping (bundled, per branch convention)**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-014 → done; QV-015 status.

### Change Log

- **2026-07-02 — QV-015 job framework (idempotency + jobs_runs + Celery/Beat).** Built the reusable job
  skeleton: `run_key`, `JobRunLedger` (idempotent `ON CONFLICT` start via `UNIQUE (job_name, run_key)`),
  `run_job` lifecycle + structlog, and Celery Beat/retry wiring with a `sample_scheduled_job` proven
  end-to-end (eager, no broker). Verified the pre-existing `jobs_runs` table (`0012`) — no new migration.
  16 new tests, 147 total green; ruff/mypy-strict/import-linter clean; framework+ledger 100% covered.
  Live worker/Beat/Redis run deferred → PV-004. Reconciled QV-014 → done.

---
baseline_commit: e7c1eadfbf1342b6589d639a1c4d5bcaf6233c09
---

# Story 8.1: QV-062 — Backtest spec + schema (async)

Status: done

**Epic:** EPIC-BT (Epic 8) · **Points:** 5 · **Depends:** QV-007 (tenant context + EntitlementService), QV-015 (job framework), QV-005 (entitlement seed)

> **First story of Epic 8 (Backtesting).** Scope is the **async submit/poll plumbing** only: validate a backtest `spec`, persist it (tenant-scoped, RLS), enqueue a Celery task, and let the user poll status. The **real backtest engine is QV-065** — this story ships a clearly-labelled engine **seam** (placeholder) so the queued→running→succeeded lifecycle works end-to-end. No look-ahead/survivorship logic here (that's QV-063/064/066).

## Story

As a user, I want to submit a backtest and poll for results, so long runs don't block me.

## Acceptance Criteria

1. **Schema VERIFY (no migration)** — the `backtests` table already exists (migration `0011_backtests.py`, tenant-scoped RLS `FORCE` + `backtests_isolation` policy): `id, tenant_id, user_id, spec jsonb, status ∈ {queued,running,succeeded,failed} (CHECK, default 'queued'), started_at, finished_at, result_ref, metrics jsonb, model_version, weights_version, error, created_at`. Add an **integration test** confirming the table shape + RLS (tenant isolation) + the status CHECK. **Do NOT write a new migration** (grep `CREATE TABLE backtests` — it's there; a duplicate fails CI on a fresh DB).
   [Source: `0011_backtests.py`; `03` §4.3; [[forward-declared-schema-migrations]]]

2. **`POST /api/v1/backtests`** — body `{ "spec": { … } }` validated by a Pydantic `BacktestSpec` (allow-listed enums, `extra="forbid"`): `type` (`factor_strategy`), `universe` (`NIFTY200`), `rules` (`rank_by` ∈ score fields, `top_n` 1–200, `rebalance` ∈ `monthly|weekly|quarterly`), `start`/`end` (ISO dates, `start < end`), `costs_bps` (0–500), `benchmark` (str). On success: create a `backtests` row (`status='queued'`, `spec` stored as JSONB, `user_id`+`tenant_id` from the token), enqueue the Celery task, and return **`202 Accepted`** with `{ id, status: "queued" }`.
   - Invalid spec → **422 `validation_error`**.
   [Source: `04` §3.6]

3. **Entitlement gating (two-tier)** — the seed grants `backtest` (Free=false, Pro=true, Quant=true) and `backtest_full` (Free/Pro=false, Quant=true):
   - No `backtest` flag → **403 `entitlement_exceeded`** (Free can't run backtests).
   - A **custom/long range** (range > ~1 year, i.e. `end - start > 366 days`) requires `backtest_full` → Pro without it → 403; Pro within the 1-year preset window → allowed; Quant → always allowed.
   [Source: `04` §3.6 "Quant tier for full range"; `seed_reference.sql` `backtest`/`backtest_full`; QV-005]

4. **`GET /api/v1/backtests/{id}`** — poll: returns `{ id, status, spec, metrics?, result_ref?, error?, created_at, started_at?, finished_at? }` for the caller's own backtest; **404 `not_found`** for unknown/foreign (RLS-invisible). On `succeeded`, `metrics` + `result_ref` are populated; on `failed`, `error` is set.
   [Source: `04` §3.6]

5. **`GET /api/v1/backtests`** — list the caller's backtests (newest first), status + spec summary. Tenant-scoped (RLS).
   [Source: `04` §3.6; mirrors `/screens`, `/alerts` list]

6. **Async task seam (`run_backtest`)** — a Celery task (registered on `celery_app`) that, given a `backtest_id`: on a **privileged session** (background job, bypasses RLS like `evaluate_alerts`) marks `status='running'`+`started_at`, runs the **`BacktestEngine.run(spec)` seam**, then marks `succeeded` (+`metrics`, `result_ref`, `finished_at`) or `failed` (+`error`). Idempotent: a non-`queued` backtest is a no-op (re-delivery guard). **The engine is a placeholder for QV-065** — it returns an empty-but-valid `BacktestResult(metrics={}, result_ref=None)` and is documented as such; QV-065 swaps in the real rebalance-loop compute. The lifecycle (queued→running→succeeded) must work end-to-end so polling is demonstrable.
   [Source: `06` job catalog; QV-065 is the engine]

7. **Tests** — unit (`BacktestSpec` validation incl. bad enums/dates → error; the range→`backtest_full` rule) + integration (POST → 202 queued; run the task → succeeded with the placeholder result; GET poll reflects status; Free → 403; Pro long-range → 403; **cross-tenant GET → 404**; unknown → 404). All integration tests `@pytest.mark.integration` (run in `backend-rls`). Coverage ≥80% on new modules.
   [Source: testing rules; QV-061 isolation precedent]

---

## Dev Notes

### Architecture & placement

- **Backtest domain lives in `analytics`** (architecture: "Analytics owns … scoring/**backtest** services"). Keep the DAG: `api|jobs → … → analytics → market_data|news → identity → core|schemas`. New files:
  - `analytics/backtest.py` — `BacktestResult` dataclass + `BacktestEngine` protocol/class with a **placeholder `run(spec) -> BacktestResult`** (QV-065 replaces the body). Pure, no I/O.
  - `analytics/backtests.py` (repo) — `create_backtest`, `get_backtest`, `list_backtests` (RLS tenant session) + `mark_running`/`mark_succeeded`/`mark_failed` (called by the job on a privileged session). Raw parameterized SQL like the other repos (`# nosec`-free; bound params).
  - `schemas/backtest.py` — `BacktestSpec`, `BacktestRules`, `SubmitBacktestRequest {spec}`, `BacktestResponse` (poll), `BacktestListItem`. All request models `ConfigDict(extra="forbid")` (QV-079).
  - `api/routes_backtests.py` — `POST /backtests` (202), `GET /backtests/{id}`, `GET /backtests` — mirror `routes_screens.py` / `routes_alerts.py` (tenant session + `Envelope`).
  - `jobs/backtest.py` — `run_backtest` Celery task (privileged session, status lifecycle, `run_job`-style idempotency).
- **Modified:** `api/app.py` (register `backtests_router` + a `BacktestNotFound → 404` handler), `jobs/celery_app.py` (`include` `quantvista.jobs.backtest`).
- **No migration.** Python 3.13, mypy strict, ruff 0.16.x. Money/costs as Decimal-or-int on the wire; store `spec`/`metrics` as JSONB.

### Async model (this is the crux)

`POST` is the request boundary (tenant RLS session): validate → `create_backtest` (row `queued`) → `run_backtest.delay(str(id))` → return **202** `{id, status:"queued"}`. The **task runs outside any request**, so it uses `privileged_session_scope()` (bypasses RLS) to load the backtest by id, read `spec`, and update status — exactly how `AlertEvaluationService`/`NotificationDeliveryService` (QV-048/049) run cross-tenant background work. Guard idempotency: only act if the row is still `queued` (Celery is at-least-once).

**Testing the task:** don't rely on a running worker. In prod the route calls `.delay()`; in tests, assert the row is `queued` + the task is registered, then **call `run_backtest(backtest_id)` directly** and assert it transitions to `succeeded` (mirrors the QV-048 evaluate_alerts test that calls the service directly). Do NOT set Celery eager globally.

### Entitlement enforcement

`EntitlementService.check(tenant_id, "backtest")` raises `EntitlementExceeded` (→ 403) when the flag is false — same pattern as `require_entitlement("optimization")` in optimize. But the range gate is **conditional on the spec**, so do it in the handler (not a static `Depends`):
```
entitlements.check(ctx.tenant_id, "backtest")                      # submit gate (Free → 403)
if (spec.end - spec.start).days > 366:
    entitlements.check(ctx.tenant_id, "backtest_full")            # custom/long range (Pro-limited → 403)
```
(Resolve entitlement AFTER validating the spec so a malformed spec is a 422, not a 403.) There's no per-plan *limit* row here — both keys are flags (`limit_int NULL, flag_bool`). `EntitlementService.check` already treats a flag key correctly (see QV-007 stub + QV-005 seed).

### Spec validation (allow-list discipline — project rule)

`spec` is user JSON persisted as JSONB and later executed by the engine — so validate strictly at the edge (like the screener/alert allow-lists): closed `Literal` sets for `type`/`universe`/`rebalance`/`rank_by`, numeric bounds for `top_n`/`costs_bps`, `date` types for `start`/`end` with a cross-field `start < end` validator, `extra="forbid"` to reject unknown keys. Store the **validated** spec (`model_dump(mode="json")`) so the JSONB is canonical. The engine (QV-065) re-reads it via the same `BacktestSpec` model.

### Backend contracts to mirror (read these)

- `api/routes_screens.py` / `api/routes_alerts.py` — the tenant-scoped CRUD shape (`get_tenant_session`, `Envelope.ok`, `X → 404` handlers, list/create). Mirror for `routes_backtests.py`. **`POST` returns 202, not 201** — set `status_code=202` and return `Envelope.ok({"id":…, "status":"queued"})`.
- `analytics/saved_screens.py` — repo pattern (RLS tenant session, parameterized SQL, `_row` mappers). Mirror for `analytics/backtests.py`.
- `jobs/scoring.py` — Celery task wiring: `from quantvista.jobs.celery_app import app`, `@app.task`, `privileged_session_scope()`, `run_job`/`run_key` for idempotent logging. Mirror for `jobs/backtest.py` (`run_key("backtest", backtest_id)`).
- `api/app.py` — where routers + error handlers register; add `backtests_router` + `BacktestNotFound`.

### Canonical envelope + status codes

Standard envelope `{success,data,error,meta}`. `202` for the queued submit (a success — use `Envelope.ok` with `status_code=202`). Canonical error codes: `validation_error`(422), `entitlement_exceeded`(403), `not_found`(404). `BacktestNotFound` maps to `not_found` like `PortfolioNotFound`.

### Previous-story / epic intelligence

- **QV-061 (just merged):** every tenant-scoped feature needs a cross-tenant 404 test (CI-gated in `backend-rls`) — include one for `GET /backtests/{id}`. The `get_X → 404` guard + RLS is the isolation pattern; backtests already have RLS in 0011.
- **QV-079:** request-body schemas use `extra="forbid"`; API responses carry `Cache-Control: no-store` (already global) — nothing to add.
- **Forward-declared schema:** 0011 pre-created `backtests` (also `saved_screens` was 0014, alerts 0010). VERIFY, don't migrate.
- **Job idempotency (QV-015):** compute a `run_key`, guard on status; Celery is at-least-once.
- The **result artifact** (`result_ref` → object store / Parquet) is fully realized in QV-067; here `result_ref` stays nullable (placeholder engine sets none).

### Git intelligence (recent)

`e7c1ead` QV-061 isolation · `49664f3` QV-060 risk/rebalance UI · `66667dd` QV-079 security. The async-job + entitlement + RLS-CRUD patterns are all established; this story composes them for backtests. No new dependency.

### Project context reference

See `_bmad-output/project-context.md`: rule #2 (RLS + cross-tenant denial test — required CI gate), #4 (PIT correctness — *deferred to QV-063/066*, but the spec must record `start/end` faithfully for the engine to honour later), #5 (forward-only migrations — none here), framework rules (envelope, cursor pagination, canonical error codes), jobs rules (idempotent + keyed). Related: [[forward-declared-schema-migrations]], [[ci-required-status-checks]], [[backend-layout-quantvista-namespace]].

---

## Tasks / Subtasks

### Task 1: Schema verify + spec model
- [x] 1a. Integration test `tests/integration/test_backtests_schema.py` (or fold into the API test): assert `backtests` columns + status CHECK + RLS isolation (a B-bound session can't see A's row). No migration.
- [x] 1b. `schemas/backtest.py` — `BacktestRules`, `BacktestSpec` (allow-listed `Literal`s, numeric bounds, `date` fields, `start<end` validator, `extra="forbid"`), `SubmitBacktestRequest`, `BacktestResponse`, `BacktestListItem`
- [x] 1c. Unit test `tests/test_backtest_spec.py` — valid spec parses; bad enum/`top_n`/`costs_bps`/`start>=end`/unknown-field → `ValidationError`

### Task 2: Repository (analytics/backtests.py)
- [x] 2a. `create_backtest(session, tenant_id, user_id, spec) -> row` (RLS tenant session; spec as JSONB)
- [x] 2b. `get_backtest(session, id) -> row | None`, `list_backtests(session) -> rows` (RLS-scoped, newest first)
- [x] 2c. `mark_running`/`mark_succeeded(metrics, result_ref)`/`mark_failed(error)` — status transitions with `started_at`/`finished_at` (used by the job on a privileged session); idempotent status guard

### Task 3: Engine seam (analytics/backtest.py)
- [x] 3a. `BacktestResult` dataclass (`metrics: dict`, `result_ref: str | None`) + `BacktestEngine.run(spec: BacktestSpec) -> BacktestResult` — **placeholder** returning `BacktestResult({}, None)`, clearly commented "engine implemented in QV-065"
- [x] 3b. Unit test asserting the placeholder returns an empty-but-valid result (guards the seam contract until QV-065)

### Task 4: Async task (jobs/backtest.py)
- [x] 4a. `run_backtest(backtest_id)` Celery task: privileged session → guard `status=='queued'` → `mark_running` → `BacktestEngine().run(spec)` → `mark_succeeded` (or `mark_failed` on exception) → structured log via `run_job`/`run_key("backtest", id)`
- [x] 4b. Register in `jobs/celery_app.py` (`include` `quantvista.jobs.backtest`)
- [x] 4c. Integration test: create a queued backtest → call `run_backtest(id)` directly → assert `succeeded` + `finished_at` set + metrics `{}`; second call is a no-op (idempotent)

### Task 5: API (routes_backtests.py + app wiring)
- [x] 5a. `POST /api/v1/backtests` — validate spec (422), entitlement `backtest` then conditional `backtest_full` (403), `create_backtest` (queued), `run_backtest.delay(str(id))`, return **202** `{id,status}`
- [x] 5b. `GET /api/v1/backtests/{id}` — poll (own → full row; unknown/foreign → 404 `BacktestNotFound`)
- [x] 5c. `GET /api/v1/backtests` — list own (newest first)
- [x] 5d. Register `backtests_router` + `BacktestNotFound → not_found` handler in `api/app.py`
- [x] 5e. Integration tests: 202 submit + poll flow; Free → 403; Pro >1y range → 403 (+ Pro ≤1y allowed, Quant full allowed); **cross-tenant GET → 404**; unknown → 404; bad spec → 422

### Task 6: Gates + sprint status
- [x] 6a. Full-tree backend gates: `ruff check . && ruff format --check . && mypy && lint-imports && bandit -c pyproject.toml -r src/ -ll -q && pip-audit --skip-editable && pytest` — green
- [x] 6b. Coverage ≥80% on `analytics/backtest.py`, `analytics/backtests.py`, `schemas/backtest.py`, `jobs/backtest.py`, `api/routes_backtests.py`
- [x] 6c. Update `sprint-status.yaml` → review; fill Dev Agent Record

---

## Dev Agent Record

### Debug Log

- **DAG blocker (the key design decision):** the route needs to enqueue a Celery task, but `api` and `jobs` are **independent sibling composition roots** in the import-linter DAG — `api → jobs` is forbidden. Resolved with a **producer seam in `core`** (`core/tasks.py::enqueue`) that publishes **by task name** via a publish-only `Celery(broker=…)` client (no worker-app import). `core` may import the third-party `celery` (foundation-purity forbids only domain contexts). The worker (`jobs.celery_app`, name `quantvista.run_backtest`) consumes it. `lint-imports` 3/3.
- mypy: `session.execute(...).rowcount` isn't on the `Result` type → rewrote `mark_running` to `UPDATE … RETURNING id` + `one_or_none()` (typed, and still the atomic queued-guard). Also added `quantvista.jobs.backtest` to the `disallow_untyped_decorators = false` mypy override (Celery's `@app.task` is untyped) — same as the other job modules.
- Test isolation from the broker: patched the `enqueue` seam to a no-op in an autouse fixture, then invoked `run_backtest(id)` **directly** to simulate the worker (per the story) — no eager mode, no live broker needed.

### Completion Notes List

- **Schema (Task 1):** VERIFY only — `backtests` is forward-declared in `0011` (RLS FORCE, status CHECK). Integration test asserts columns + CHECK rejection + cross-tenant RLS invisibility. **No migration.**
- **Spec (Task 1):** `schemas/backtest.py` — `BacktestSpec`/`BacktestRules` with allow-listed `Literal`s, numeric bounds, real dates, a `start<end` validator, `extra="forbid"`. Stored as validated JSONB (`model_dump(mode="json")`).
- **Repo (Task 2):** `analytics/backtests.py` — `create`/`get`/`list` on the RLS tenant session; `mark_running` (atomic queued-guard via `RETURNING`) / `mark_succeeded` / `mark_failed` for the job on a privileged session.
- **Engine seam (Task 3):** `analytics/backtest.py` — `BacktestEngine.run` **placeholder** returning `BacktestResult({}, None)`, clearly labelled "QV-065 fills the real compute".
- **Async task (Task 4):** `jobs/backtest.py::run_backtest` — privileged session, `mark_running` guard, engine seam, `mark_succeeded`/`mark_failed`, `run_job`/`run_key("backtest", id)` logging + ledger idempotency. Registered in `celery_app.include`.
- **API (Task 5):** `routes_backtests.py` — `POST /backtests` (validate → entitlement `backtest`, then `backtest_full` for >366-day range → create queued → `enqueue` → **202**), `GET /backtests/{id}` (poll; foreign/unknown → 404), `GET /backtests` (list own). Wired into `app.py` (+ `BacktestNotFound → 404`).
- **Entitlement:** Free (flag off) → 403; Pro ≤1y preset → 202, Pro >1y → 403 (needs `backtest_full`); Quant full → 202. Resolved **after** spec validation (bad spec = 422, not 403).
- **Tests:** 14 unit (spec) + 1 (engine) + 10 API integration + 3 schema = **26 new**; incl. the failure path (engine raises → `failed`+error), idempotent re-run, and cross-tenant 404 (QV-061 pattern). Coverage 96% on the new modules (all ≥80%).
- **Gates:** full suite **694 passed / 5 skipped**; ruff/format/mypy(262)/lint-imports(3/3)/bandit/pip-audit green. No migration, no new dependency.
- Reconcile ride-along: QV-061 marked **done** (merged PR #70) in this branch (prior-story reconcile).

### File List

**New**
- `backend/src/quantvista/schemas/backtest.py` — `BacktestSpec`/`BacktestRules`/request+response DTOs
- `backend/src/quantvista/analytics/backtest.py` — `BacktestEngine` seam (placeholder) + `BacktestResult`
- `backend/src/quantvista/analytics/backtests.py` — repo (create/get/list + status transitions)
- `backend/src/quantvista/core/tasks.py` — `enqueue` producer seam (send by name; DAG-legal)
- `backend/src/quantvista/jobs/backtest.py` — `run_backtest` Celery task
- `backend/src/quantvista/api/routes_backtests.py` — POST/GET/list endpoints
- `backend/tests/test_backtest_spec.py`, `tests/test_backtest_engine.py`
- `backend/tests/integration/test_api_backtests.py`, `tests/integration/test_backtests_schema.py`

**Modified**
- `backend/src/quantvista/api/app.py` — register `backtests_router` + `BacktestNotFound` handler
- `backend/src/quantvista/jobs/celery_app.py` — `include` `quantvista.jobs.backtest`
- `backend/pyproject.toml` — mypy untyped-decorator override for `jobs.backtest`

### Change Log

- **2026-07-27 — QV-062 backtest spec + schema (async).** Async submit/poll for backtests: verified the forward-declared `backtests` schema (no migration); allow-listed `BacktestSpec`; `POST /backtests → 202 queued` + `GET` poll + list, two-tier entitlement (`backtest` / `backtest_full`); `run_backtest` Celery task driving queued→running→succeeded/failed on a privileged session with a **placeholder engine seam** (real compute = QV-065). Introduced `core.tasks.enqueue` (send-by-name) to keep `api`↔`jobs` DAG-independent. 694 passed/5 skipped; 96% new-module coverage; no migration/dependency. Starts Epic 8. Also reconciles QV-061 → done.

---
baseline_commit: e88d68d4f434a876cd4904b9e5a12b02eb0a7a7b
---

# Story 2.1: QV-004 — PostgreSQL + Alembic + RLS scaffolding

Status: review

<!-- DB AVAILABLE (2026-06-20): a local PostgreSQL 18.4 server runs on localhost:5432 (Homebrew
postgresql@18). The `quantvista` DB + non-superuser `quantvista_app` role are provisioned, migrations
0001→0012 apply (head 0012, 45 tables), and RLS isolation was verified manually (app role sees only
its tenant). So QV-004 is NOT Docker-gated — it uses the local Postgres directly. PV-001 (the QV-002
docker-compose stack) is now DECOUPLED from QV-004 and remains independently open. -->

## Story

As an **engineer**,
I want **the application-side database layer and tenant-isolation primitives (SQLAlchemy engine/session that sets `app.tenant_id` per request, a privileged reference-data path, and a cross-tenant denial test wired into CI)**,
so that **tenant data is isolated by construction via PostgreSQL RLS — not by hopeful application code**.

> Canonical ID **QV-004** · Epic 2 (EPIC-IDN) · `[BE]` · 8pts · Sprint 00 · depends: **QV-002 (done)**
> Authoritative detail: `plans/sprints/sprint-00-foundations.md` §QV-004. RLS/data: `plans/03-data-architecture.md` §2, §9; security: `plans/07-security-and-compliance.md` §3.

## Acceptance Criteria

1. **Alembic is wired for the app and the expand/contract convention is documented.** Migrations `0001`→`0012` apply cleanly to a fresh Postgres via `alembic upgrade head` (from `backend/src/quantvista/db`); the forward-only, expand→backfill→contract convention (`plans/03` §9) is documented in `backend/src/quantvista/db/README.md` (already present — confirm/extend, don't rewrite).
2. **A SQLAlchemy engine/session layer exists** in `quantvista/core/db.py`: an **app engine** (non-superuser, from `Settings.database_url`) and a **privileged engine** (admin/reference-data role, from an admin URL) — the app engine connects as a role **without `BYPASSRLS`**.
3. **Per-request tenant binding:** a `session_scope(tenant_id)` (or FastAPI dependency) opens a transaction and issues `SET LOCAL app.tenant_id = :tid` so the existing `app_current_tenant()` (migration `0001`) resolves it; the binding lasts exactly one transaction. A **privileged session helper** (no tenant binding, reference-data role) exists for global/job writes to non-RLS tables.
4. **Cross-tenant access denial test passes — and runs in CI against a real Postgres.** An integration test creates two tenants, writes a row under tenant A, switches the session to tenant B, and asserts **zero rows visible** and a **write under B's context cannot touch A's row**. CI (`.github/workflows/ci.yml`) gains a Postgres **service container**, applies migrations, and runs these RLS tests as the **non-superuser app role** (a superuser would bypass RLS and make the test pass falsely).
5. **Test isolation & markers:** DB-backed tests use a pytest marker (e.g. `@pytest.mark.integration`) and shared fixtures (engine, migrated schema, per-test transaction rollback). Unit tests still run with **no** database; integration tests are skipped/деselected when `DATABASE_URL`/Postgres is absent, so local unit runs and the existing CI unit job stay green.
6. **No regressions:** all existing gates stay green — ruff, mypy --strict, pytest (existing 25 unit tests), import-linter (new `core.db` must not break the DAG), frontend unchanged.

## Tasks / Subtasks

- [x] **Task 1 — App DB engine/session layer** (AC: #2, #3)
  - [x] Add `quantvista/core/db.py`: `make_engine(url)` (SQLAlchemy 2.0, `psycopg` driver, sane pool); a cached **app engine** (`Settings.database_url`) and **privileged engine** (admin URL — add `admin_database_url` to `core.config.Settings`).
  - [x] `@contextmanager session_scope(tenant_id: UUID | None = None)`: begin a transaction; if `tenant_id`, `execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})`; commit/rollback; close. Use `SET LOCAL` (transaction-scoped) — never session-wide `SET`.
  - [x] `privileged_session_scope()`: uses the privileged engine, sets **no** tenant — for reference/global table writes by jobs. Document that it must never write tenant tables.
  - [x] FastAPI dependency `get_session()` (tenant-bound) for later API stories — wire the value source in QV-007; here it can take tenant from an injected `ITenantContext` placeholder or a param.
- [x] **Task 2 — Config: admin/privileged URL** (AC: #2)
  - [x] Add `admin_database_url` to `Settings` (maps `ADMIN_DATABASE_URL`, already in `.env.example`/compose). Keep the app `database_url` as the non-superuser role.
- [x] **Task 3 — DB test harness** (AC: #4, #5)
  - [x] Add `backend/tests/conftest.py` fixtures: detect Postgres via env; `pytest.mark.integration`; an engine fixture; a fixture that ensures `alembic upgrade head` ran once against the test DB; per-test transaction + rollback for isolation.
  - [x] Skip integration tests cleanly when no Postgres is configured (so `pytest` with no DB still passes — preserves the existing unit job).
- [x] **Task 4 — Cross-tenant RLS denial test** (AC: #4)
  - [x] `backend/tests/integration/test_rls_isolation.py`: using an **existing** tenant-scoped RLS table (e.g. `watchlists` or `saved_screens` — do NOT add a throwaway demo table; real RLS tables already exist from `0002`/`0008`/`0009`), create tenant A + tenant B, insert under A (`session_scope(A)`), then under `session_scope(B)` assert the row is invisible and that B cannot update/delete it. Connect as the **non-superuser app role**.
  - [x] Add a negative check: with **no** `app.tenant_id` set, tenant-table reads return zero rows (policy denies).
- [x] **Task 5 — CI: Postgres service + RLS gate** (AC: #4, #6)
  - [x] Extend `.github/workflows/ci.yml` `backend-tests` (or add a `backend-rls` job): a `postgres:16` **service** with health check; create the non-superuser `quantvista_app` role (reuse `scripts/db/00-create-app-role.sql`); run `alembic upgrade head` as admin; run `pytest -m integration` as the **app role**. Keep the existing no-DB unit job intact. Ensure `ci-success` still aggregates correctly.
- [x] **Task 6 — Docs + regression** (AC: #1, #6)
  - [x] Confirm/extend the expand/contract + RLS notes in `backend/src/quantvista/db/README.md`; document the app-vs-privileged engine split and the "non-superuser app role" rule in `backend/README.md`.
  - [x] Re-run all gates (ruff/mypy/pytest unit/import-linter) green; run the integration suite against a Postgres and confirm the denial test passes.

## Dev Notes

### ⚠️ Implementation gate (read first)
**dev-story for QV-004 requires a reachable PostgreSQL** — the RLS denial test (AC #4) cannot be written/verified without one, and it must connect as a **non-superuser** role (a superuser/`BYPASSRLS` connection silently passes the test). This ties to **PV-001** (`docs/pending-verifications.md`): the QV-002 local stack provides exactly that Postgres + the `quantvista_app` role. So: close PV-001 (or otherwise provide a Postgres) **before** running dev-story here. Writing this spec needs no DB.

### Scope discipline
This is the **application-side** DB + isolation layer. The **schema already exists** — migrations `0001`→`0012` create all tables, the `app_current_tenant()` helper, and RLS policies (`USING (tenant_id = app_current_tenant()) WITH CHECK (...)`, `ENABLE`+`FORCE ROW LEVEL SECURITY`). **Do NOT add new schema/migrations for tables that already exist, and do NOT re-create RLS policies.** Build the engine/session/test layer that *uses* them. No auth, no API endpoints (those are QV-006/QV-007).

### What already exists (build on it — verified in the migrations)
- `app_current_tenant()` (migration `0001`): `SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid`. Returns NULL when unset → RLS policies deny. Your `SET LOCAL app.tenant_id = '<uuid>'` feeds this.
- RLS policy pattern (`0002` and later): every tenant table has `ENABLE` + **`FORCE` ROW LEVEL SECURITY** and a `<tbl>_isolation` policy `USING (tenant_id = app_current_tenant()) WITH CHECK (...)`. `FORCE` means even the table owner is subject to RLS — but a **superuser or a role with `BYPASSRLS` still bypasses it**, so tests/app MUST use the non-superuser `quantvista_app` role.
- Tenant-scoped tables available for the denial test: `tenants`, `users`, `memberships`, `subscriptions` (`0002`); `portfolios`, `portfolio_positions` (`0008`); `watchlists`, `watchlist_items`, `saved_screens` (`0009`); `alert_rules`, `alert_events`, `notifications` (`0010`); `backtests` (`0011`). Pick a simple one (`watchlists`/`saved_screens`).
- Global/reference tables (NO `tenant_id`, NO RLS, written by the **privileged** role): `markets`, `stocks`, `daily_prices`, `fundamentals`, … and Platform `audit_log`, `jobs_runs` (`0012`).
- `quantvista.core.config.Settings` exists (`database_url` = app role; `ADMIN_DATABASE_URL` already in `.env.example`/compose). `scripts/db/00-create-app-role.sql` creates the non-superuser `quantvista_app` role with DML grants.
- `quantvista/core/db.py` does **not** exist yet — this story creates it. `core` is the DAG foundation (imports no domain context); SQLAlchemy is external — import-linter stays green.

### Engine/session design (SQLAlchemy 2.0, psycopg)
- Two engines: **app** (`Settings.database_url`, non-superuser) for all tenant-table access; **privileged** (`admin_database_url`) for reference/global writes by jobs. Single-source the maker; cache engines.
- `SET LOCAL` is **transaction-scoped** — it must be issued inside the same transaction as the queries and resets at commit/rollback. Pattern:
  ```python
  with engine.begin() as conn:                      # one transaction
      if tenant_id:
          conn.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
      ...                                            # queries see only this tenant's rows
  ```
- Bind parameter for the UUID as a **string**; do not f-string it into SQL (injection / and `SET LOCAL` doesn't take normal params in all drivers — use `set_config('app.tenant_id', :tid, true)` if the parameterized `SET LOCAL` form misbehaves: `SELECT set_config('app.tenant_id', :tid, true)`). Prefer `set_config(..., true)` (the `true` = local/transaction scope) — it parameterizes cleanly.
- App role must connect **without `BYPASSRLS`** (project-context #2). Never point the app engine at the Postgres superuser.

### CI design (the AC #4 gate)
- Add a `postgres:16` service to the backend tests job (health-checked). Steps: create `quantvista_app` role (run `scripts/db/00-create-app-role.sql` as admin), `alembic upgrade head` (admin), then `pytest -m integration` with `DATABASE_URL` pointing at the **app role** and `ADMIN_DATABASE_URL` at admin.
- Keep the existing **no-DB unit job** (don't make all tests require Postgres). Gate integration tests behind the marker + env detection so local `pytest` (no DB) and the current unit job stay green. Confirm `ci-success` still aggregates (it joins `needs.*.result`).

### Testing standards
- Unit (no DB): `session_scope` issues the right `SET LOCAL`/`set_config` SQL (assert via a mock/echo) — keep at least one DB-free unit test for the SQL it emits.
- Integration (Postgres, `-m integration`): the cross-tenant denial test (AC #4) is the centerpiece and a **required CI gate** (project-context Testing Rules: "cross-tenant denial test" is mandatory). AAA, behavior-named. Also assert the no-tenant-set case denies.
- Coverage ≥80% on the new `core/db.py`.

### Project Structure Notes
- New: `quantvista/core/db.py`; `backend/tests/conftest.py`; `backend/tests/integration/test_rls_isolation.py` (+ `backend/tests/integration/__init__.py`).
- Modified: `quantvista/core/config.py` (`admin_database_url`); `.github/workflows/ci.yml` (Postgres service + RLS step); `backend/pyproject.toml` (register `integration` marker; maybe `[tool.pytest.ini_options] markers`); `backend/README.md` / `db/README.md` (docs).
- Do **not** modify the migrations or RLS policies. Do **not** add a demo table — use existing RLS tables.

### References
- [Source: plans/sprints/sprint-00-foundations.md#QV-004]
- [Source: plans/03-data-architecture.md#2] — RLS isolation model; [#9] — expand/contract migrations
- [Source: plans/07-security-and-compliance.md#3] — RLS/authz cross-tenant denial as a CI gate
- [Source: backend/src/quantvista/db/migrations/versions/0001_extensions_and_helpers.py] — `app_current_tenant()`
- [Source: backend/src/quantvista/db/migrations/versions/0002_identity_tenancy_billing.py] — RLS policy pattern, FORCE RLS
- [Source: _bmad-output/project-context.md#2] — RLS enforced by Postgres, non-superuser app role, mandatory cross-tenant denial test
- [Source: _bmad-output/implementation-artifacts/1-2-qv-002-local-dev-environment-docker-compose.md] — app vs admin DB roles, `quantvista_app`, compose Postgres
- [Source: docs/pending-verifications.md] — PV-001 gate (live Postgres availability)

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Opus 4.8) via BMAD dev-story workflow.

### Debug Log References

- Verified the schema applies on local **PostgreSQL 18.4** (Homebrew) before coding: provisioned
  `quantvista` DB + non-superuser `quantvista_app` role, `alembic upgrade head` → `0012` (45 tables),
  and manually proved RLS (app role sees only its tenant). De-risked the whole story up front.
- mypy: `Session.execute()` is typed `Result[Any]` which lacks `.rowcount` (a `CursorResult` member)
  → `cast("CursorResult[Any]", …)` in the UPDATE/DELETE isolation assertions.
- ruff E501 on a long SQL line → wrapped; `database_url` default re-wrapped by `ruff format`.
- `psycopg` `connect_args={"connect_timeout": 2}` used in the reachability probe so the no-DB unit
  job / machines without Postgres skip integration tests fast instead of hanging.

### Completion Notes List

- **All 6 ACs satisfied; all tasks/subtasks complete. Status → review.** Backend gates green: ruff,
  ruff format, mypy --strict (50 files), import-linter (new `core.db`/`core.config` edges allowed),
  pytest **30 passed** (26 unit + **4 RLS integration**).
- **Not Docker-gated** — implemented and fully verified against the native local Postgres. (PV-001,
  the container stack, stays separately open.)
- **`quantvista/core/db.py`** (Task 1): app engine (non-superuser, RLS) + privileged engine
  (reference/admin); `session_scope(tenant_id)` binds `app.tenant_id` per-transaction via
  `set_config('app.tenant_id', …, true)`; `privileged_session_scope()` for global writes.
- **Config** (Task 2): added `admin_database_url`; `database_url` default corrected to the
  `quantvista_app` non-superuser role.
- **Cross-tenant denial test** (Task 4, the AC #4 gate): `tests/integration/test_rls_isolation.py` —
  tenant A sees only A, B only B, **B cannot see/update/delete A's rows**, unbound session sees
  nothing. Runs as the non-superuser app role via `core.db.session_scope`.
- **Test harness** (Task 3): `conftest.py` auto-skips integration tests when no Postgres is reachable
  (keeps the DB-free unit job green); `two_tenants` fixture seeds A/B + a user + a watchlist each
  (admin-seeded, cascade teardown); `integration` marker registered in `pyproject.toml`.
- **CI** (Task 5): new `backend-rls` job — `postgres:16` service, creates the non-superuser role
  (`scripts/db/00-create-app-role.sql`), `alembic upgrade head` as admin, grants, then
  `pytest -m integration` **as the app role**; wired into `ci-success`. Existing no-DB unit job
  unchanged.
- **Docs** (Task 6): `backend/README.md` gains a "Database access & tenant isolation (RLS)" section;
  `db/README.md` migration note updated (Docker *or* native Postgres).
- **Per the user's request:** added an optional, idempotent, local-dev-only
  `scripts/db/dev-seed-tenant.sql` (a `tenant-test` tenant + user + watchlist) and seeded it locally
  so it's visible in pgAdmin. It is NOT reference data and is never auto-run (real tenants come from
  registration, QV-006). The RLS tests are unaffected (they assert on their own ephemeral tenants).
- **No new runtime deps**; `httpx` already present, `psycopg`/`sqlalchemy` already declared.

### File List

**New:**
- `backend/src/quantvista/core/db.py`
- `backend/tests/conftest.py`
- `backend/tests/test_db_unit.py`
- `backend/tests/integration/__init__.py`
- `backend/tests/integration/test_rls_isolation.py`
- `scripts/db/dev-seed-tenant.sql`

**Modified:**
- `backend/src/quantvista/core/config.py` (`admin_database_url`; app role default)
- `backend/pyproject.toml` (`integration` marker)
- `.github/workflows/ci.yml` (`backend-rls` job + `ci-success` wiring)
- `backend/README.md`, `backend/src/quantvista/db/README.md` (docs)
- this story file (frontmatter `baseline_commit`, tasks, Dev Agent Record, Status)

## Change Log

| Date | Change |
|------|--------|
| 2026-06-20 | QV-004 implemented: app-side DB layer (`core/db.py` — app vs privileged engines, per-transaction `app.tenant_id` binding), cross-tenant RLS denial test (`session_scope`, runs as non-superuser app role), `conftest` reachability-gated integration harness, CI `backend-rls` job with a Postgres service, docs, and an optional local dev-seed tenant. Verified on native local PostgreSQL 18.4 (not Docker-gated). All gates green (30 tests). Status → review. |

---
baseline_commit: f3dde2a41fa1bcd5925fefb129b2d141fe160f7e
---

# Story 1.2: QV-002 — Local dev environment (docker-compose)

Status: done

<!-- Merged on accepted risk: the live `docker compose up` smoke test (AC #1–3) is deferred to a
Docker-capable machine and tracked as PV-001 in docs/pending-verifications.md. Hard gate: must be
green before QV-004. -->


<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **engineer**,
I want **one-command local infrastructure (`docker-compose up`) that boots the full stack**,
so that **I can run, seed, and exercise the whole system locally without hand-wiring services**.

> Canonical ID **QV-002** · Epic 1 (EPIC-PLAT) · `[PLAT]` · 3pts · Sprint 00 · depends: **QV-001 (done)**
> Authoritative detail: `plans/sprints/sprint-00-foundations.md` §QV-002. Infra spec: `plans/08-infra-devops-observability.md` §2.

## Acceptance Criteria

1. **`docker-compose up` brings up all seven services:** `postgres`, `redis`, `minio`, `api`, `worker`, `beat`, `web` — on a shared network (`quantvista-net`) with named volumes (`pg_data`, `redis_data`, `minio_data`). The three backend roles (`api`/`worker`/`beat`) run from **one backend image**, differing only by `command`.
2. **Schema + seed run automatically on `up`:** a one-shot step applies Alembic migrations (`alembic upgrade head`, revisions `0001`→`0012`) and loads `seed_reference.sql` (idempotent). `api`/`worker`/`beat` start only **after** it completes successfully.
3. **Health endpoints are green:** the `api` service exposes `GET /api/v1/health` returning the standard envelope (`{success:true, data:{status:"ok"}, error:null, meta:{...}}`) with HTTP 200; the compose `api` healthcheck polls it and reports `healthy`. `web` (Next.js) serves its root and reports healthy.
4. **A minimal-but-real backend app exists** to satisfy #3: a FastAPI app factory (`quantvista.api.app:create_app`) mounting `/api/v1/health`, a Celery app (`quantvista.jobs.celery_app`) used by `worker`/`beat`, and env-driven config via **pydantic-settings** (`quantvista.core.config`). No business endpoints/tasks beyond health + a trivial Celery ping.
5. **Multi-stage, non-root Dockerfiles:** `backend/Dockerfile` (Python 3.13-slim, multi-stage, pinned base, non-root user, default CMD = api) and `frontend/Dockerfile` (Next.js `standalone` build, non-root). Same backend image is reused for `worker`/`beat` via `command` override.
6. **`.env.example` documents every config var** (DATABASE_URL, REDIS_URL, MinIO/S3 endpoint+keys, app env) and `docker-compose` reads from `.env`. **No real secrets committed.**
7. **README documents setup:** `docker-compose up`, what each service is, ports, how to reach health endpoints, how to run migrations/seed, and how to tear down (`down -v`). Root `README.md` and/or `backend/README.md` updated.
8. **No regressions:** all QV-001 gates stay green — `ruff check` + `ruff format --check`, `mypy --strict`, `pytest`, `lint-imports` (the new app code must not break the module DAG), plus frontend `tsc`/`eslint`/`build`.

## Tasks / Subtasks

- [x] **Task 1 — Env-driven config (pydantic-settings)** (AC: #4, #6)
  - [x] Add `quantvista/core/config.py`: a `Settings(BaseSettings)` with `app_env`, `database_url`, `redis_url`, `s3_endpoint_url`, `s3_access_key`, `s3_secret_key`, `s3_bucket`. Load from env; provide a cached `get_settings()`.
  - [x] Create `.env.example` (repo root) with every var and safe local defaults (MinIO creds, local Postgres URL). Ensure `.gitignore` keeps `.env` out and `!.env.example` in (already configured).
- [x] **Task 2 — Minimal FastAPI app (health)** (AC: #3, #4)
  - [x] Add `quantvista/api/app.py` with `create_app() -> FastAPI`, mounting a router at `/api/v1` with `GET /health` that returns the standard envelope (`quantvista.schemas.envelope.Envelope.ok({"status": "ok"})`). Keep an ASGI entrypoint (`app = create_app()`) for uvicorn.
  - [ ] (Optional, recommended) `GET /api/v1/health/ready` that checks DB + Redis connectivity and returns `upstream_unavailable` envelope on failure — keep liveness (`/health`) dependency-free. _(Deferred — not required for AC; liveness `/health` is shipped.)_
- [x] **Task 3 — Celery app for worker/beat** (AC: #1, #4)
  - [x] Add `quantvista/jobs/celery_app.py` constructing the Celery app from `Settings.redis_url` (broker + backend), with a trivial `ping` task to prove worker liveness. Beat schedule can be empty (real jobs are QV-015+).
- [x] **Task 4 — Backend Dockerfile** (AC: #5, #1)
  - [x] `backend/Dockerfile`: multi-stage (builder installs from `pyproject.toml`), `python:3.13-slim` runtime, **non-root** user, `WORKDIR /app`, package installed (`pip install .`). Default `CMD` runs the api role (`uvicorn quantvista.api.app:app --host 0.0.0.0 --port 8000`). `.dockerignore` excludes `.venv`, `__pycache__`, tests artifacts, `node_modules`.
  - [x] Confirm the SAME image runs `worker` (`celery -A quantvista.jobs.celery_app worker -l info`) and `beat` (`celery -A quantvista.jobs.celery_app beat -l info`) via compose `command` override — no role-specific image.
- [x] **Task 5 — Frontend Dockerfile (web)** (AC: #1, #5)
  - [x] Set `output: "standalone"` in `frontend/next.config.ts`. Add `frontend/Dockerfile`: multi-stage (deps → build → runner), non-root, copies `.next/standalone` + static, runs `node server.js` on port 3000.
- [x] **Task 6 — docker-compose.yml** (AC: #1, #2, #3)
  - [x] Author root `docker-compose.yml` with services `postgres` (16-alpine, env user/db, `pg_data`, healthcheck `pg_isready`), `redis` (7-alpine, `redis_data`, healthcheck `redis-cli ping`), `minio` (console + api ports, `minio_data`, healthcheck), `api`, `worker`, `beat` (build `backend/`, env from `.env`), `web` (build `frontend/`).
  - [x] Add a one-shot **`migrate`** service (backend image) that runs `alembic upgrade head` then loads the seed (see Dev Notes → "Seeding"); `api`/`worker`/`beat` use `depends_on: { migrate: { condition: service_completed_successfully } }` and `postgres`/`redis` `condition: service_healthy`.
  - [x] Define network `quantvista-net` and volumes `pg_data`, `redis_data`, `minio_data`. Map ports: api `8000`, web `3000`, postgres `5432`, redis `6379`, minio `9000`/`9001`.
- [ ] **Task 7 — Docs + verification** (AC: #7, #8) — _docs done; live verification deferred & tracked as PV-001 (merged on accepted risk)_
  - [x] Update `README.md` (root) and `backend/README.md` with the compose workflow, service table, ports, health URLs, seed/migrate behavior, and `docker-compose down -v`.
  - [ ] ⏸️ **DEFERRED (tracked as PV-001) — verify end-to-end:** `docker compose up` → all services healthy; `curl localhost:8000/api/v1/health` → 200 envelope; `curl localhost:3000` → 200; `worker`/`beat` logs ready; seed loaded. This Mac (macOS 12 Monterey) cannot run a Docker engine, so QV-002 was merged on accepted risk with this run deferred to a Docker-capable machine. **Hard gate: before QV-004.** Tracked in `docs/pending-verifications.md` (PV-001).
  - [x] Re-run the QV-001 quality gates locally and confirm green (no regressions).

## Dev Notes

### Scope discipline (read first)
QV-002 makes the stack **runnable**, not feature-rich. The only application code is: env config, a health endpoint, a Celery app + ping task. **No business endpoints, no models, no real jobs.** Resist building auth/data/jobs here — those are QV-004/QV-006/QV-015. Keep the new code inside the module DAG (api/jobs are composition roots; `core.config` is foundation).

### What QV-001 already established (build on it — don't re-create)
- Backend is the `quantvista` namespace at `backend/src/quantvista/`; **Python 3.13**; venv `backend/.venv`; editable install (`pip install -e ".[dev]"`) makes `quantvista` importable.
- `pyproject.toml` already declares runtime deps (`fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `alembic`, `celery`, `redis`, `psycopg[binary]`) — **they're declared but were installed `--no-deps` locally**. QV-002's Dockerfile installs them for real (`pip install .`), and CI already installs `-e ".[dev]"` with full deps. If anything fails to resolve on 3.13, that surfaces here first.
- `api/__init__.py` and `jobs/__init__.py` are intentionally empty composition roots — this is where they get their first real modules (`api/app.py`, `jobs/celery_app.py`).
- Response envelope lives at `quantvista.schemas.envelope` (`Envelope.ok(...)`, `Envelope.fail(code, message)`, `ERROR_STATUS` map). **Reuse it for `/health`** — do not invent a new response shape (project-context: standard envelope on every endpoint).
- DB layer is at `backend/src/quantvista/db/` (alembic.ini `script_location = migrations`, URL from `$DATABASE_URL`, `target_metadata=None`). `alembic upgrade head` was verified to resolve; **QV-002 is the first time it runs against a live Postgres.**
- import-linter (`backend/.importlinter`, `root_package=quantvista`) enforces the DAG. New imports of `fastapi`/`celery`/`pydantic_settings` are external (fine). `api` may import `quantvista.schemas`; `jobs`/`api` may import `quantvista.core`. **Do not import a domain context's internals** — none are needed for health/ping anyway.
- CI (QV-003, merged) runs ruff/format/mypy/pytest/lint-imports on `backend/**` and tsc/eslint/build on `frontend/**`, Python 3.13. Keep all green.

### Same image, three roles (critical pattern — plans/08 §2, project-context #6)
One `backend/Dockerfile` → one image. Compose runs it three times with different `command`:
- `api`: `uvicorn quantvista.api.app:app --host 0.0.0.0 --port 8000`
- `worker`: `celery -A quantvista.jobs.celery_app worker -l info`
- `beat`: `celery -A quantvista.jobs.celery_app beat -l info`

Domain logic is single-sourced; **never fork logic per role**. The Dockerfile's default `CMD` is the api role.

### Seeding (AC #2) — recommended approach
`seed_reference.sql` is **SQL**, and the backend slim image won't have `psql`. Cleanest pattern:
- **`migrate` one-shot** (backend image): runs `alembic upgrade head` (schema). Then either (a) it also loads the seed via a tiny Python loader that executes the SQL over SQLAlchemy, or (b) a separate **`seed` one-shot on the `postgres:16` image** runs `psql "$DATABASE_URL" -f /seed/seed_reference.sql` (mount `backend/src/quantvista/db/seeds/`). Prefer (b) — no `psql` in the app image, keeps it lean.
- Both are idempotent (migrations are forward-only; seed is idempotent by design). `api`/`worker`/`beat` gate on `migrate`/`seed` via `depends_on: condition: service_completed_successfully`.

### RLS / database role (do NOT mask tenant isolation locally — project-context #2)
- The app must connect as a **non-superuser without `BYPASSRLS`**; a superuser silently bypasses RLS and hides cross-tenant bugs. For local compose, provision a dedicated app role (e.g. `quantvista`) that is **not** superuser; migrations may run as a more-privileged role if needed. Document this — do not let `DATABASE_URL` point the app at the Postgres superuser.
- `DATABASE_URL` form: `postgresql+psycopg://quantvista:<pw>@postgres:5432/quantvista` (service hostname `postgres` on `quantvista-net`).

### Health endpoint shape (AC #3)
```
GET /api/v1/health  -> 200
{ "success": true, "data": {"status": "ok"}, "error": null, "meta": {} }
```
Keep liveness dependency-free so it stays green during boot. Put DB/Redis checks behind a separate `/health/ready` if added. Compose `api` healthcheck: `curl -fsS http://localhost:8000/api/v1/health` (add `curl` to the runtime image, or use a Python one-liner to avoid bloat).

### Config (pydantic-settings) — env, never hardcoded
`quantvista/core/config.py` → `Settings(BaseSettings)` reading env (`model_config = SettingsConfigDict(env_file=".env", ...)`). No secrets in source. The same Settings object backs api, worker, and beat. `get_settings()` should be cached (`functools.lru_cache`).

### Frontend `web` container
- `next.config.ts`: add `output: "standalone"` so the runner image is small. The existing app (layout + TanStack Query provider) builds today; just containerize it. Non-root runner, port 3000. `web` doesn't depend on `migrate` (no DB), but may depend on `api` being up if it calls it (it doesn't yet).

### Files being created (NEW) and touched (UPDATE)
- **NEW:** `docker-compose.yml`, `backend/Dockerfile`, `backend/.dockerignore`, `frontend/Dockerfile`, `frontend/.dockerignore`, `.env.example`, `quantvista/core/config.py`, `quantvista/api/app.py` (+ a small `routers/health.py` if you split), `quantvista/jobs/celery_app.py`, tests for config/health/celery-app.
- **UPDATE:** `frontend/next.config.ts` (`output: "standalone"`), `README.md`, `backend/README.md`, possibly `backend/pyproject.toml` (only if a dep pin needs adjusting — avoid unless required).
- **PRESERVE:** the Alembic chain and `env.py`/`alembic.ini` (unchanged); the import-linter contracts; the response envelope.

### Testing standards
- Add `pytest` tests: `Settings` loads from env (monkeypatched), `/api/v1/health` returns the envelope with `success=True` (use `fastapi.testclient.TestClient`), and the Celery app constructs with the configured broker URL. AAA structure, behavior-named.
- These run without Docker (unit-level). The full `docker-compose up` health verification is a manual/integration check captured in Completion Notes (CI doesn't run compose).
- Coverage ≥80% is the project gate; the new app code is small and testable — cover it.

### Project Structure Notes
- New app modules sit in existing packages: `api/app.py`, `jobs/celery_app.py`, `core/config.py` — consistent with the QV-001 layout. No new top-level packages.
- Docker/compose artifacts live at repo root (`docker-compose.yml`, `.env.example`) and per-app (`backend/Dockerfile`, `frontend/Dockerfile`).
- `nginx` and the optional `finbert` model server from `plans/08` §2 are **out of scope** for QV-002 (AC lists 7 services); add them in later infra/sentiment stories.

### References
- [Source: plans/sprints/sprint-00-foundations.md#QV-002] — story, ACs, notes
- [Source: plans/08-infra-devops-observability.md#2-containerization] — compose services, network/volumes, same-image-three-roles, multi-stage non-root
- [Source: plans/08-infra-devops-observability.md#1] — `local` environment row (docker-compose, MinIO for S3)
- [Source: _bmad-output/project-context.md#6] — same image, three roles
- [Source: _bmad-output/project-context.md#2] — RLS: app connects as non-superuser without BYPASSRLS
- [Source: _bmad-output/project-context.md#framework-specific-rules] — standard response envelope, `/api/v1`
- [Source: _bmad-output/implementation-artifacts/1-1-qv-001-monorepo-module-skeleton-with-dependency-linting.md] — established layout, gates, envelope, alembic location

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Opus 4.8) via BMAD dev-story workflow.

### Debug Log References

- mypy strict flagged: generator fixtures typed `-> None` (→ `Iterator[None]`), `Settings(_env_file=...)` untyped kwarg (→ `Settings()`), and `celery` lacking py.typed. Fixed via fixture typing + two scoped `[[tool.mypy.overrides]]` (celery `ignore_missing_imports`; `quantvista.jobs.celery_app` `disallow_untyped_decorators = false`).
- ruff `UP`/format: reformatted `core/config.py` long line.
- `httpx` added to dev deps (required by `fastapi.testclient.TestClient`). Starlette emits a deprecation warning recommending `httpx2`; harmless, tests pass.
- Seed file uses `BEGIN/COMMIT` + dollar-quoted functions → not safely splittable; seeded via a dedicated `seed` one-shot on the `postgres` image (`psql -f`), not the slim app image.

### Completion Notes List

- **Status: in-progress — Tasks 1–6 complete & validated; Task 7 docs done, live `docker compose up` smoke test (AC #1–3) PENDING** (no Docker engine on this macOS 12 machine). See `plans/sprints/sprint-00-foundations.md` → QV-002 deferred-verification note. Recommended gate: **before QV-004**.
- **Statically verified green:** backend ruff (lint+format), mypy --strict (45 files), pytest (25 passed: 18 prior + 7 new), import-linter (3 contracts kept — new `api→schemas`/`jobs→core` edges allowed); frontend tsc/eslint/`next build`; `docker compose config` renders all 9 services valid.
- **Same image, three roles:** one `backend/Dockerfile` (multi-stage, non-root, `python:3.13-slim`); compose runs it as `api` (default CMD), `worker`, `beat` via `command` override + shared `image: quantvista-backend:local`.
- **First real app wiring:** `quantvista.api.app:create_app` + `/api/v1/health` reusing `schemas.envelope`; `quantvista.jobs.celery_app` (Redis broker/result + `ping`); `quantvista.core.config` (pydantic-settings). No business logic.
- **RLS guardrail honored:** `scripts/db/00-create-app-role.sql` provisions a **non-superuser `quantvista_app`** role (initdb hook); app services connect as it, `migrate`/`seed` use the admin role. So local RLS isn't silently masked (project-context #2).
- **Seeding:** one-shot `migrate` (alembic upgrade head, admin role) → one-shot `seed` (`psql -f seed_reference.sql`); `api`/`worker`/`beat` gate on `service_completed_successfully`.
- **Deferred by design:** optional `/health/ready` (DB/Redis deep check) — liveness `/health` shipped; MinIO bucket bootstrap (S3 unused until later); `nginx`/`finbert` from plans/08 (out of AC scope).
- **What the live run must confirm later:** all services reach healthy; `curl :8000/api/v1/health` → 200 envelope; `curl :3000` → 200; worker/beat logs ready; seed rows present; images build (first real full-deps `pip install` + Next standalone build).

### File List

**New — backend app code + tests:**
- `backend/src/quantvista/core/config.py`
- `backend/src/quantvista/api/app.py`
- `backend/src/quantvista/jobs/celery_app.py`
- `backend/tests/test_config.py`, `backend/tests/test_health.py`, `backend/tests/test_celery_app.py`

**New — containerization / local stack:**
- `docker-compose.yml`
- `backend/Dockerfile`, `backend/.dockerignore`
- `frontend/Dockerfile`, `frontend/.dockerignore`
- `scripts/db/00-create-app-role.sql`
- `.env.example`

**Modified:**
- `backend/pyproject.toml` (httpx dev dep; mypy overrides for celery)
- `frontend/next.config.ts` (`output: "standalone"`)
- `README.md`, `backend/README.md` (compose workflow, service table, ports)
- `plans/sprints/sprint-00-foundations.md` (QV-002 deferred-verification note)
- this story file (frontmatter `baseline_commit`, tasks, Dev Agent Record, Status)

**Untracked (local only, gitignored):** `.env` (copied from `.env.example` for local runs)

## Change Log

| Date | Change |
|------|--------|
| 2026-06-19 | QV-002 implemented (Tasks 1–6): pydantic-settings config, FastAPI `/api/v1/health` (standard envelope), Celery app + `ping`, multi-stage non-root backend + frontend Dockerfiles, `docker-compose.yml` (postgres/redis/minio + migrate/seed one-shots + api/worker/beat/web), non-superuser app DB role for RLS, README/compose docs. All static gates green; `docker compose config` valid. **Live `docker compose up` verification deferred** (no Docker engine on macOS 12) — documented in plans, gate before QV-004. Status: in-progress. |

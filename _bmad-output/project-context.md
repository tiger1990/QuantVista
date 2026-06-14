---
project_name: 'FinanceStockManager (QuantVista)'
user_name: 'Deepak Sir'
date: '2026-06-14'
sections_completed: ['technology_stack', 'language_specific', 'framework_specific', 'jobs_scheduler', 'quant_domain', 'testing', 'code_quality', 'workflow', 'anti_patterns']
existing_patterns_found: 9
status: 'complete'
rule_count: 40
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

> **State of the repo (updated 2026-06-15, QV-001):** The **module skeleton now exists**. Backend
> is the `quantvista` namespace package at `backend/src/quantvista/` (bounded contexts + `api, jobs,
> schemas, db`), with the Alembic DB layer relocated from repo-root `db/` to
> `backend/src/quantvista/db/` (revisions `0001`→`0012` unchanged). `import-linter` enforces the
> module DAG; Ruff/mypy/pytest are green. Frontend is a Next.js app at `frontend/`. Business logic is
> still **not** implemented — contexts hold `interfaces.py` (Protocol/ABC) + empty placeholders. The
> rich design lives in `plans/` (00–09 + futures) and the sprint backlog in `plans/sprints/`; treat
> `plans/` as the source of truth for behavior until code catches up.

---

## Technology Stack & Versions

| Layer | Choice | Notes |
|-------|--------|-------|
| Backend language | **Python 3.13** | `backend/pyproject.toml` (`requires-python >=3.13`); venv at `backend/.venv` |
| Backend framework | **FastAPI** | REST under `/api/v1`; same image runs `api` / `worker` / `beat` by command |
| Async/jobs | **Celery + Celery Beat**, **Redis** (cache · queue · Redis Streams event bus) | worker autoscale by queue depth (KEDA) in prod |
| Database | **PostgreSQL** (RLS, monthly range partitions, bitemporal PIT) | migrations are hand-written DDL |
| Migrations | **Alembic** (`db/`) — forward-only in prod, expand/contract | `DATABASE_URL` injected via env in `db/migrations/env.py`; no creds in `alembic.ini` |
| ORM | **SQLAlchemy** (planned) | `target_metadata = None` today — autogenerate is OFF until models exist |
| Frontend | **Next.js / TypeScript / MUI**, TanStack Query, Recharts | not scaffolded yet |
| Object store | **S3** (prod) / **MinIO** (local) — parquet, exports | |
| Billing | **Stripe** | entitlements cache keyed `ent:{tenant_id}`, busted on webhook |
| Cloud / IaC | **AWS** (`ap-south-1`), **Terraform**, **Kubernetes + Helm** | image-based promotion local→staging→prod |
| Lint / type / format | **Ruff** (lint + format), **mypy**, **pytest** | Alembic post-write hook runs `ruff format` on new migrations |
| CI | **GitHub Actions** | PR gate: ruff · mypy · unit · **RLS/authz tests** · **bias regression** · frontend lint+type+unit · build · SAST + secret scan + pip-audit |
| Config / secrets | **pydantic-settings** (env-driven); **AWS Secrets Manager/SSM** | never hardcode secrets |

---

## Critical Implementation Rules

These are the unobvious, load-bearing rules. Violating one is a real bug, not a style nit.

### 1. Two data domains — never blur them
- **Global / reference & market data** (`stocks`, `daily_prices`, `fundamentals`, `index_constituents`, scores, news): **no `tenant_id`, no RLS**, shared by all tenants, **written only by background jobs**.
- **Tenant data** (`users`, `portfolios`, `watchlists`, `saved_screens`, `alert_rules`, `backtests`, `subscriptions`): **`tenant_id` on every row, RLS-enforced**, written by user actions.
- A new table belongs to exactly one domain. If it has `tenant_id`, it MUST get an RLS policy.

### 2. Tenant isolation is enforced by Postgres RLS, not app code
- Every request runs `SET LOCAL app.tenant_id = '<uuid>'` inside the request transaction. The DB function `app_current_tenant()` (migration `0001`) reads it.
- RLS policy pattern (see `0002`): `USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())`.
- A privileged/reference-data role is used for job writes to global tables. **Never** bypass RLS for tenant tables.
- **Every tenant-scoped feature needs a cross-tenant-access-denial test** — this is a required CI gate, not optional.

### 3. Module boundaries are hard seams (modular monolith)
- Bounded contexts: `identity`, `market_data`, `news`, `analytics`, `portfolio`, `alerts`, `core` (Platform/Core; named `core` to avoid shadowing stdlib `platform`), plus `api`, `jobs`, `schemas`, `db` — all under `backend/src/quantvista/`.
- Modules talk **only** through published interfaces (Python `Protocol`/ABC, e.g. `IAuthService`, `IMarketDataProvider`, `IEntitlementService`) or domain events on the Redis Streams bus.
- **No cross-module table access. No shared mutable state.** `import-linter` enforces the dependency DAG in CI — a forbidden import fails the build.

### 4. Point-in-time correctness is non-negotiable
- Scores and backtests may use **only data knowable at that time** — no look-ahead bias, no survivorship bias.
- `fundamentals` is **bitemporal/PIT**; `index_constituents` is point-in-time membership; delisted names keep `delisted_on` set and **stay queryable**.
- Backtests must read the *historical* Nifty 200, not today's. **Bias regression tests** run in CI.

### 5. Migrations: forward-only, expand/contract, hand-written DDL
- Alembic, reviewed in PRs. **Never destructive in a single release** — expand (add) → migrate data → contract (remove) across releases for zero downtime.
- Migrations are hand-written (partitioning, bitemporal columns, RLS) — not autogenerated. RLS policies ship *in* the migration.
- Use the helpers from `0001`: `app_current_tenant()`, `set_updated_at()` trigger, `create_month_partition()`. `daily_prices`/`technical_indicators` are **monthly range-partitioned on `date`**.
- Keep the constraint/index naming convention from `env.py` (`ix_`, `uq_`, `ck_`, `fk_`, `pk_`) so future autogenerate diffs stay stable.

### 6. Same image, three roles
- One backend Docker image runs `api` (uvicorn), `worker` (Celery), `beat` (Celery scheduler) selected by command. Domain logic is single-sourced — **don't fork logic per role**.

### 7. Research, not advice (product + compliance constraint)
- Every recommendation-shaped output is a **"research signal"** with a non-advice disclaimer and a transparent, inspectable derivation. **No "you should buy X."** This is a locked decision (D1), not a copy choice.

### 8. Data licensing is a gating risk
- **Never** let `yfinance`/Yahoo or unofficial scrapers back a paying tier — not licensed for commercial redistribution. All external market data enters via the `IMarketDataProvider` interface so the vendor can be swapped without touching analytics.

### 9. Secrets & config
- Config is env-driven via `pydantic-settings`; secrets come from AWS Secrets Manager/SSM (External Secrets Operator in k8s). `DATABASE_URL` is injected at runtime. **No secrets in source or `alembic.ini`.**

---

## Implementation Rules by Category

### Language-Specific Rules (Python 3.13)
- Modern typing only: `X | None`, `list[...]`, `dict[...]` — not `Optional`/`List`. Start files with `from __future__ import annotations` (matches `db/migrations`).
- `UUID` PKs via `gen_random_uuid()` (pgcrypto). Financial values are `Decimal`/`NUMERIC`, **never `float`**.
- mypy must pass; type all public interfaces. Module domain interfaces are `Protocol`/ABC (`IAuthService`, `IMarketDataProvider`, …).

### Framework-Specific Rules (FastAPI / Next.js)
- **Contract-first:** FastAPI-generated OpenAPI is the source of truth; frontend consumes a *generated typed client* — never hand-write API types.
- **Standard response envelope** on every endpoint: `{ success, data, error, meta }`. Errors: `success:false, data:null, error:{code,message}`.
- Canonical error codes → status: `validation_error`(422), `unauthenticated`(401), `forbidden`(403), `entitlement_exceeded`(402/403), `rate_limited`(429), `conflict`(409), `infeasible`(422), `upstream_unavailable`(503), `internal_error`(500).
- Mutating endpoints honor an `Idempotency-Key` header (replays return the original result). Pagination is **cursor-based** (`?limit&cursor`, `meta.next_cursor`) — not offset.
- All routes under `/api/v1`. Frontend server state via TanStack Query; charts via Recharts.

### Jobs / Scheduler Rules (Celery + Beat)
- Every job is **idempotent & keyed** — compute a `run_key` (e.g. `prices:NSE:2026-06-13`); re-running is a safe no-op via idempotent upserts (Celery is at-least-once).
- Pipeline is a **DAG driven by domain events**, not chained crons. **Backfill = same task, different date window** — never a separate code path.
- Retries: exponential backoff + jitter → dead-letter on exhaustion → alert after N failures. Structured logs per run (`run_key`, duration, rows in/out, outcome) to `jobs_runs`.
- Schedules use **IST cadence** but timestamps are stored/computed in **UTC**.

### Quant / Domain Rules
- Factors implement `Factor.compute(ctx, stock_id, as_of) -> float | None`. Normalize **cross-sectionally**: z-score within sector → winsorize → 0–100 percentile.
- A factor returning `None` is **excluded and the category re-normalized** over available data — don't impute zeros.
- `ScoreWeights` are **versioned** (`weights_version`); persist `factor_values` so every score's decomposition is reproducible/auditable.
- Optimizer uses **Ledoit-Wolf shrinkage covariance** (sample covariance is unstable); infeasible problems return `error.code="infeasible"` with the binding constraint.
- **Backtests are deterministic:** store full `spec` + `model_version` + `weights_version`; seed any stochastic step so the same spec reproduces the same result.

### Testing Rules
- CI gates beyond unit tests: **RLS/authz tests** (cross-tenant denial), **bias-regression tests** (no look-ahead/survivorship), frontend lint+type+unit. Coverage **≥80%**.
- E2E via **Playwright** (runs against staging post-merge). AAA structure; descriptive behavior-named tests.

### Code Quality & Workflow Rules
- **Ruff** for lint + format; mypy strict on public APIs. Many small files (200–400 lines, 800 max), organized by bounded context.
- Commits: conventional (`feat/fix/refactor/…`). Branching: `main` (protected) + short-lived `feature/*`; PRs need green checks + review.

### Critical Don't-Miss (anti-patterns)
- ❌ Reaching into another module's tables/internals — go through its interface or an event.
- ❌ Adding `tenant_id` without an RLS policy + a cross-tenant denial test.
- ❌ `float` for money/weights; offset pagination; bypassing the response envelope.
- ❌ `yfinance`/scrapers behind a paid tier; look-ahead data in scores/backtests.
- ❌ Destructive migration in one release (always expand/contract).

---

## Conventions

- **Branching:** trunk-ish — `main` (deployable, protected) + short-lived `feature/*`; required reviews + green checks.
- **Coverage gate:** unit test coverage **≥ 80%** in CI.
- **Auth:** Argon2id password hashing; short-lived access JWT + rotating refresh (httpOnly cookie for web) with refresh-reuse detection.
- **Money:** weights/positions use `NUMERIC` (never float) for financial values.

---

## Key References (source of truth)

| Topic | Doc |
|-------|-----|
| Locked decisions, product principles | `plans/00-overview-and-decisions.md` |
| PRD | `plans/01-prd.md` |
| Architecture, modules/seams | `plans/02-architecture.md` |
| Data model, RLS, PIT, partitioning, migrations §9 | `plans/03-data-architecture.md` |
| API contracts | `plans/04-api-contracts.md` |
| Domain & quant | `plans/05-domain-and-quant.md` |
| Scheduler & jobs | `plans/06-scheduler-and-jobs.md` |
| Security & compliance | `plans/07-security-and-compliance.md` |
| Infra / DevOps / observability | `plans/08-infra-devops-observability.md` |
| Roadmap & delivery (DoD) | `plans/09-roadmap-and-delivery.md` |
| Sprint backlog (current: Sprint 00) | `plans/sprints/` |
| DB schema (live code) | `db/` (revisions `0001`→`0012`, `db/README.md`) |

---

## Usage Guidelines

**For AI agents:**
- Read this file before implementing any code. Follow all rules exactly; when in doubt, prefer the more restrictive option.
- `plans/` is the authoritative spec until app code exists — cross-check the referenced doc before inventing behavior.

**For humans:**
- Keep it lean and agent-focused. Update when the stack or a locked decision changes; review periodically and drop rules that become obvious once code lands.
- Re-run GPC once the backend/frontend exist — there will be real code patterns to capture then (today it's schema-only).

Last Updated: 2026-06-14

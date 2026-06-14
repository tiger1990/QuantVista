# Development Guide

> What you can actually run today is the **database layer**. App/frontend setup is documented from
> design (`plans/08`) and will become runnable as Sprint 00 lands.

## Prerequisites

- Python 3.13, PostgreSQL (with `pgcrypto`, `btree_gin` available), Alembic.
- Planned (not yet required): Redis, MinIO/S3, Docker + docker-compose, Node.js (frontend).

## Database — runnable now

```bash
export DATABASE_URL=postgresql+psycopg://quantvista:***@localhost:5432/quantvista
cd backend/src/quantvista/db    # relocated from repo-root db/ in QV-001
alembic upgrade head            # apply all migrations 0001→0012
alembic current                 # show current revision
alembic downgrade -1            # roll back one
psql "$DATABASE_URL" -f seeds/seed_reference.sql   # idempotent reference seed
```

**Important DB rules:**
- The app must connect as a **non-superuser without `BYPASSRLS`** — RLS is the isolation layer and a
  superuser bypasses it.
- Each request/transaction sets `SET LOCAL app.tenant_id = '<uuid>'` before touching tenant tables.
- Migrations are **forward-only in prod**; use **expand → backfill → contract** for zero-downtime
  changes. Never destructive in a single release.
- Partition maintenance: schedule monthly `create_month_partition()` for `daily_prices`,
  `technical_indicators`, `factor_values`, `scores` (or use pg_partman).

## Backend app — scaffolded (QV-001)

- Importable package `quantvista` under `backend/src/quantvista/`, organised by bounded context:
  `identity, market_data, news, analytics, portfolio, alerts, core` + `api, jobs, schemas, db`. Layer
  concerns (`models/services/repositories`) live inside each context, not as shared top-level folders.
- `import-linter` (`backend/.importlinter`, `root_package = quantvista`) enforces the module DAG —
  a forbidden cross-context import fails `lint-imports` (and CI via QV-003).
- The `db/` folder was relocated to `backend/src/quantvista/db` with no migration-history change.
- Tooling: Ruff (lint+format), mypy (strict), pytest, import-linter — all green on the skeleton.
- One image runs `api` / `worker` / `beat` by command.
- `docker-compose up` (QV-002) brings up postgres, redis, minio, api, worker, beat, web.

## Tooling & quality

| Concern | Tool / rule |
|---------|-------------|
| Lint + format | **Ruff** (Alembic post-write hook runs `ruff format` on new migrations) |
| Types | **mypy** (strict on public APIs) |
| Tests | **pytest**; coverage **≥80%**; **RLS/authz** + **bias-regression** tests are CI gates |
| E2E | **Playwright** against staging |
| Config / secrets | `pydantic-settings`; AWS Secrets Manager/SSM. **No secrets in source or `alembic.ini`** |

## Git / workflow

- **No git repo yet** — initialize before the BMAD dev loop (`git init`).
- Trunk-ish: `main` (protected) + short-lived `feature/*`; conventional commits; PRs need review + green checks.

## Conventions agents must follow

See `_bmad-output/project-context.md` for the full, lean rule set (language, framework, jobs, quant,
testing, anti-patterns).

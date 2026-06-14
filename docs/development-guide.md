# Development Guide

> What you can actually run today is the **database layer**. App/frontend setup is documented from
> design (`plans/08`) and will become runnable as Sprint 00 lands.

## Prerequisites

- Python 3.12, PostgreSQL (with `pgcrypto`, `btree_gin` available), Alembic.
- Planned (not yet required): Redis, MinIO/S3, Docker + docker-compose, Node.js (frontend).

## Database — runnable now

```bash
export DATABASE_URL=postgresql+psycopg://quantvista:***@localhost:5432/quantvista
cd db
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

## Backend app — planned (Sprint 00, QV-001/002)

- Package layout mirrors bounded contexts: `identity, market_data, news, analytics, portfolio, alerts,
  platform/core` + `api, jobs, schemas, db`. `import-linter` enforces the module DAG (forbidden import
  fails CI). The `db/` folder moves to `backend/src/db` with no migration-history change.
- One image runs `api` / `worker` / `beat` by command.
- `docker-compose up` (planned) brings up postgres, redis, minio, api, worker, beat, web.

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

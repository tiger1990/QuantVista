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
- Partition maintenance is **automatic** (QV-104): the Beat-scheduled `quantvista.ensure_partitions`
  keeps three months of monthly partitions ahead for every date-range-partitioned table, discovering
  them from the catalog. Migrations create only the current + next month, so before QV-104 rows
  silently fell into `_default` from month two — no error, just lost pruning.

## Running the stack locally

Two processes must be up, and **neither survives a reboot**. Both have silent failure modes that
read as application bugs, so check them first when something looks broken:

```bash
# 1. API — the --reload flag is not optional
cd backend && uvicorn quantvista.api.app:app --port 8000 --reload

# 2. Worker — backtests are routed to the `user` queue
cd backend && celery -A quantvista.jobs.celery_app worker -Q user --concurrency 2
```

| Symptom | Cause |
|---|---|
| A valid request 404s; the UI blames your inputs | `uvicorn` started **without `--reload`** is serving code from before a merged story. Check `lsof -nP -iTCP:8000 -sTCP:LISTEN` — two processes can both bind, and the one on `127.0.0.1` wins. |
| A submitted backtest sits at `queued` forever | No worker on the **`user`** queue. Compare `redis-cli llen user` with `llen celery`. |
| Every strategy metric reads `0.00%` while the benchmark looks fine | Derived data is missing. The benchmark is pure price maths and needs no indicators, which is why only one side zeroes out. |

### Seeding a usable dataset

```bash
cd backend && python scripts/dev_backfill.py          # prices → indicators → factors → scores
python scripts/dev_backfill.py --scores-last-day-only # faster; enough for /rankings only
```

Every step spans the **whole** window. Indicators are always backfilled in full because the backtest
engine ranks off `technical_indicators` at every rebalance date — one day of indicators behind a year
of prices produces a silently zeroed backtest (QV-105). If a date was computed earlier from partial
data, the QV-015 ledger considers it done; use `backfill_indicators(..., force=True)` to repair it.

Coverage is monitored rather than assumed: `data_coverage_gap_sessions` counts **trading sessions**
that have prices but no derived rows, and alerts on it. Freshness cannot catch this — derived data
can carry today's date and still be missing a year of history.

## Backend app — scaffolded (QV-001)

- Importable package `quantvista` under `backend/src/quantvista/`, organised by bounded context:
  `identity, market_data, news, analytics, portfolio, ml, alerts, core` + `api, jobs, schemas, db`. Layer
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

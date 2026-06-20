# QuantVista backend

Python **3.13** modular monolith. The importable package is `quantvista` under a `src` layout
(`backend/src/quantvista/`). Each bounded context is a hard seam — see the root `README.md` and
`plans/02-architecture.md`.

## Layout

```
src/quantvista/
├── core/          # Platform/Core: config, logging, errors, IEventBus, IAuditLogger
├── identity/      # IAuthService, IEntitlementService, ITenantContext
├── market_data/   # IMarketDataProvider, IPriceRepository, IFundamentalsRepository
├── news/          # INewsService, ISentimentService
├── analytics/     # IScoreEngine, IFactor, IBacktestEngine
├── portfolio/     # IPortfolioService, IOptimizer, IRiskEngine
├── alerts/        # IAlertService, INotificationChannel
├── schemas/       # shared DTOs + standard response envelope
├── api/           # FastAPI composition root (HTTP boundary)
├── jobs/          # Celery app + Beat schedule
└── db/            # Alembic migrations + seeds (relocated from repo-root db/)
```

Each context exposes a published `interfaces.py` (`Protocol`/ABC) — **the only thing other contexts
may import**. Layer concerns (`models.py`, `services.py`, `repositories.py`) live *inside* each
context, never as top-level shared folders; that is what keeps the module DAG enforceable.

> **Naming:** the Platform/Core context is the package `core` (not `platform`/`platform_core`) to
> avoid shadowing Python's stdlib `platform` module.

## Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"     # editable install makes `quantvista` importable for tests + import-linter
```

## Quality gates (all run on the skeleton)

```bash
ruff check . && ruff format --check .   # lint + format
mypy                                    # strict types (db/migrations excluded)
pytest                                  # unit/smoke tests
lint-imports                            # bounded-context dependency DAG (backend/.importlinter)
```

A **forbidden cross-context import fails `lint-imports`** (and, via QV-003, fails CI).

## Run in Docker (the local stack)

The backend ships **one image, three roles** (`api`/`worker`/`beat`) selected by `command`:

```bash
docker build -t quantvista-backend:local .                                  # build once
docker run --rm quantvista-backend:local                                    # api (default CMD)
docker run --rm quantvista-backend:local celery -A quantvista.jobs.celery_app worker -l info
docker run --rm quantvista-backend:local celery -A quantvista.jobs.celery_app beat -l info
```

Normally you don't run these by hand — `docker compose up` (repo root) wires `postgres`, `redis`,
`minio`, `migrate`+`seed` (one-shots), `api`, `worker`, `beat`, and `web` together. See the root
`README.md`. Config is env-driven (`quantvista.core.config`); the app connects to Postgres as the
non-superuser `quantvista_app` role so RLS is enforced.

## Database / migrations

Migrations are hand-written, forward-only, expand/contract Alembic DDL (revisions `0001`→`0012`).
The URL is injected from `$DATABASE_URL` (never stored in `alembic.ini`).

```bash
cd src/quantvista/db
DATABASE_URL=postgresql+psycopg://quantvista:***@localhost:5432/quantvista alembic upgrade head
```

> Migrations need a live Postgres. Use **Docker compose** (QV-002) *or* a native local Postgres
> (e.g. Homebrew `postgresql@18`). Without a DB you can still inspect the chain:
> `cd src/quantvista/db && alembic history`.

## Database access & tenant isolation (RLS)

`quantvista.core.db` exposes two engines and a tenant-scoped session — **this is the only sanctioned
way to touch the database**:

| Helper | Role | Use for |
|--------|------|---------|
| `session_scope(tenant_id)` | **app** (non-superuser, RLS enforced) | all tenant-scoped tables |
| `privileged_session_scope()` | **admin/reference** role | global/reference tables (job writes) only |

`session_scope(tenant_id)` opens a transaction and binds `app.tenant_id` via
`set_config('app.tenant_id', …, true)` (transaction-local), so the `app_current_tenant()` SQL
function resolves it and **RLS policies filter every query to that tenant**. The app role connects
**without `BYPASSRLS`** — a superuser would silently bypass isolation.

```python
from quantvista.core.db import session_scope

with session_scope(tenant_id) as s:        # sees only this tenant's rows
    s.execute(text("SELECT * FROM watchlists"))
```

**Cross-tenant isolation is a CI gate.** `tests/integration/test_rls_isolation.py` proves tenant A
cannot see or modify tenant B's rows (and that an unbound session sees nothing). These run as the
non-superuser app role; locally they auto-run when a Postgres is reachable, otherwise they skip:

```bash
# local: app + admin roles against your Postgres
createdb quantvista                       # if not present; then apply migrations (admin)
DATABASE_URL=...quantvista_app...  ADMIN_DATABASE_URL=...quantvista...  pytest        # all tests
pytest -m integration                     # just the RLS gate
```

Optional: seed a demo tenant to explore in psql/pgAdmin (local-dev only, never auto-run):

```bash
psql "$ADMIN_DATABASE_URL" -f ../scripts/db/dev-seed-tenant.sql
```

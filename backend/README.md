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

## Database / migrations

Migrations are hand-written, forward-only, expand/contract Alembic DDL (revisions `0001`→`0012`).
The URL is injected from `$DATABASE_URL` (never stored in `alembic.ini`).

```bash
cd src/quantvista/db
DATABASE_URL=postgresql+psycopg://quantvista:***@localhost:5432/quantvista alembic upgrade head
```

> Running migrations against a live Postgres requires the local stack from **QV-002**. Without a DB
> you can still inspect the chain: `cd src/quantvista/db && alembic history`.

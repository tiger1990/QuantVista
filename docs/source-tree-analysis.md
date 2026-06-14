# Source Tree Analysis

> Exhaustive scan, 2026-06-14. Annotated tree of what **exists today** (code is DB-layer only).

```
FinanceStockManager/
├── db/                         # ★ ONLY code that exists — database layer
│   ├── alembic.ini             # Alembic config; sqlalchemy.url blank → set from $DATABASE_URL
│   ├── README.md               # DB setup / migration usage
│   ├── seeds/
│   │   └── seed_reference.sql  # Idempotent: markets, plans, entitlements, NIFTY200 constituents
│   └── migrations/
│       ├── env.py              # Reads $DATABASE_URL; target_metadata=None (hand-written DDL); naming convention
│       ├── script.py.mako      # Migration template
│       └── versions/
│           ├── 0001_extensions_and_helpers.py     # pgcrypto, helpers, partition fn, app_current_tenant()
│           ├── 0002_identity_tenancy_billing.py   # tenants/users/memberships/plans/entitlements/subscriptions + RLS
│           ├── 0003_reference_market.py           # markets/stocks/index_constituents/corporate_actions/macro_series
│           ├── 0004_prices_partitioned.py         # daily_prices (monthly range partitions)
│           ├── 0005_fundamentals_pit.py           # fundamentals (bitemporal) + shareholding
│           ├── 0006_indicators_factors_scores.py  # technical_indicators/factor_values/scores (partitioned)
│           ├── 0007_news_sentiment.py             # news + sentiment
│           ├── 0008_portfolio_risk.py             # portfolios/positions/optimization_runs/risk_snapshots (RLS)
│           ├── 0009_watchlists_screens.py         # watchlists/items/saved_screens (RLS)
│           ├── 0010_alerts_notifications.py       # alert_rules/alert_events/notifications (RLS)
│           ├── 0011_backtests.py                  # backtests (RLS)
│           └── 0012_platform.py                   # audit_log + jobs_runs (global)
│
├── plans/                      # ★ Design source of truth (no code)
│   ├── 00-overview-and-decisions.md   # Decision log (D1–D8), product principles
│   ├── 01-prd.md                      # Product requirements
│   ├── 02-architecture.md             # Modules/seams, C4
│   ├── 03-data-architecture.md        # Data model, RLS, PIT, partitioning, migrations §9
│   ├── 04-api-contracts.md            # REST/OpenAPI, envelope, error codes
│   ├── 05-domain-and-quant.md         # Factor/Normalizer/scoring/optimizer/backtest
│   ├── 06-scheduler-and-jobs.md       # Celery jobs, idempotency, DAG
│   ├── 07-security-and-compliance.md  # Auth, secrets, non-advice posture
│   ├── 08-infra-devops-observability.md # Docker/K8s/Terraform/CI
│   ├── 09-roadmap-and-delivery.md     # Roadmap, DoD
│   ├── future-*.md                    # RIA compliance, US expansion, microservices
│   └── sprints/                       # 12 sprints (sprint-00 … sprint-12) — current backlog
│
├── design-artifacts/           # (empty) — reserved for WDS / UX outputs
├── docs/                       # ★ This documentation set (BMAD Document Project output)
├── _bmad/                      # BMAD v6.8 install (modules, config)
└── _bmad-output/               # BMAD artifacts — project-context.md (agent rules) lives here
```

## Entry points

- **Migrations:** `cd db && DATABASE_URL=... alembic upgrade head` (see development-guide.md).
- **Application entry points (api/worker/beat):** *not yet implemented.*

## Where code lands (QV-001 — scaffolded)

Backend: the `quantvista` namespace package at `backend/src/quantvista/` mirroring the bounded
contexts — `core/`, `identity/`, `market_data/`, `news/`, `analytics/`, `portfolio/`, `alerts/` +
`api/`, `jobs/`, `schemas/`, `db/` (the last relocated from repo-root `db/`). `import-linter`
enforces the module DAG. Frontend: Next.js feature-folder app at `frontend/`. Both delivered in
QV-001; the runnable local stack (docker-compose) is QV-002.

# QuantVista — Architecture (canonical for BMAD)

> **Authoritative source:** `plans/02-architecture.md` (system), `plans/03-data-architecture.md` (data),
> `plans/04-api-contracts.md` (API), `plans/05-domain-and-quant.md` (quant), `plans/06-scheduler-and-jobs.md`
> (jobs), `plans/07-security-and-compliance.md` (security), `plans/08-infra-devops-observability.md` (infra).
> Also see `docs/architecture.md` (DP-generated) and `docs/data-models.md`. This file is the BMAD-canonical
> consolidation so Phase-3 tooling (Implementation Readiness) can discover and analyze it.

## Locked decisions (drive the architecture)

| ID | Decision |
|----|----------|
| D1 | Research/analytics tool; no personalized advice |
| D2 | India first — Nifty 200; market-agnostic abstractions day one |
| D4 | **Modular monolith, pre-seamed for microservice extraction** |
| D6 | Multi-tenancy: shared DB/schema + `tenant_id` + Postgres **RLS** |
| D7 | Python 3.12 + FastAPI; Next.js/TS; PostgreSQL + Redis + Celery |
| D8 | AWS (`ap-south-1`), Terraform IaC (portable) |

## Style & strategy

Modular monolith. Each module is a **bounded context** with its own package, domain models, service layer,
and repository, exposing a **published in-process interface** (Python `Protocol`/ABC). Modules communicate
**only** through interfaces or Redis Streams domain events — never another module's internals/tables.
`import-linter` enforces the dependency DAG (forbidden import fails CI). Each seam can later become a
separate service (HTTP/gRPC + queue consumer) without a rewrite.

**Same image, three roles:** one backend image runs `api` (uvicorn), `worker` (Celery), `beat` (scheduler)
by command — domain logic single-sourced.

## Containers

Frontend (Next.js/TS/MUI · TanStack Query · Recharts) → HTTPS `/api/v1` → FastAPI (authn/z, entitlements,
rate limit, validation) → in-process module seams → PostgreSQL (RLS, partitions) · Redis (cache/queue/
Streams) · Object store (S3/MinIO). Celery workers + Beat run ingestion, indicators, scoring, sentiment,
optimization, backtests.

## Modules & ownership

| Module | Owns (tables) | Interfaces |
|--------|---------------|------------|
| Identity & Tenancy | tenants, users, memberships, plans, entitlements, subscriptions | `IAuthService`, `IEntitlementService`, `ITenantContext` |
| Market Data (reference) | stocks, daily_prices, fundamentals, shareholding, corporate_actions, index_constituents | `IMarketDataProvider`, `IPriceRepository`, `IFundamentalsRepository` |
| Analytics | technical_indicators, factor_values, scores | `Factor`, `Normalizer`, scoring/backtest services |
| Portfolio & Risk | portfolios, portfolio_positions, optimization_runs, risk_snapshots | optimizer + constraints engine |
| News & Sentiment | news, sentiment | sentiment scorer |
| Notifications & Alerts | alert_rules, alert_events, notifications | alert engine |
| Platform / Core | audit_log, jobs_runs | tenant context, event bus |

## Data architecture (see docs/data-models.md)

- **Two domains:** global reference/market (no `tenant_id`, no RLS, job-written) vs tenant-scoped
  (`tenant_id` + RLS, user-written).
- **RLS isolation:** `SET LOCAL app.tenant_id`; policy `USING/WITH CHECK (tenant_id = app_current_tenant())`;
  app connects as non-superuser without `BYPASSRLS`.
- **PIT correctness:** `fundamentals` bitemporal (`knowledge_from/to`); `index_constituents` PIT membership;
  `stocks.delisted_on` → survivorship-free history.
- **Partitioning:** `daily_prices`, `technical_indicators`, `factor_values`, `scores` monthly RANGE on `date`.
- DDL is hand-written Alembic (`db/` revisions 0001→0012); forward-only, expand/contract.

## API design

Contract-first: FastAPI OpenAPI is source of truth; frontend uses a generated typed client. REST/JSON under
`/api/v1`. Standard envelope `{ success, data, error, meta }`; canonical error codes; `Idempotency-Key` on
mutations; cursor pagination; per-tenant/per-plan rate limits.

## Quant core

`Factor.compute(ctx, stock_id, as_of) -> float | None`; cross-sectional normalization (z-score in sector →
winsorize → 0–100 percentile); versioned `ScoreWeights`; persisted `factor_values` for reproducible
decomposition; Ledoit-Wolf shrinkage covariance in the optimizer; deterministic, reproducible backtests
(`spec` + `model_version` + `weights_version`, seeded).

## Jobs & scheduling

Celery + Beat; all jobs idempotent & keyed (`run_key`); DAG driven by domain events; backfill = same task,
different window; retry backoff+jitter → dead-letter → alert; structured logs to `jobs_runs`.

## Deployment & ops

Docker (multi-stage, non-root) → docker-compose local → Kubernetes prod (HPA api, KEDA queue-depth workers,
singleton beat). Terraform IaC on AWS `ap-south-1`; managed Postgres/Redis/S3; image-based promotion
local→staging→prod. Secrets via AWS Secrets Manager/SSM.

## Testing strategy

Unit + integration; **RLS/authz cross-tenant denial** and **bias-regression** tests are required CI gates;
coverage ≥80%; Playwright E2E against staging. DoD per `plans/09-roadmap-and-delivery.md` §4.

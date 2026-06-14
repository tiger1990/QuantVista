# Architecture — QuantVista (backend/data)

> Documented design from `plans/02-architecture.md` + current `db/` code. Architecture style D4:
> **modular monolith, pre-seamed for microservice extraction**. Multi-tenancy D6: shared schema +
> `tenant_id` + Postgres RLS.

## Executive summary

A funded team parallelizes without paying full microservices ops cost by building a **modular
monolith**: each module is a bounded context with its own package, domain models, service layer, and
repository, exposing a **published in-process interface** (Python `Protocol`/ABC). Modules never reach
into another module's internals or tables — only interfaces or domain events. Each seam can later be
lifted into its own service by swapping the in-process call for HTTP/gRPC and the event handler for a
Redis Streams consumer.

## Containers (C4 L2)

```
Frontend (Next.js/TS/MUI · TanStack Query · Recharts)
        │ HTTPS  /api/v1
API layer (FastAPI: authn/z · entitlements · rate limit · validation)
        │ in-process module interfaces (seams)
 ┌──────────┬───────────┬───────────┬───────────┬──────────┬───────────────┐
 Identity   Market Data  Analytics   Portfolio   News &     Notifications
 & Tenancy  (reference)  (factors/   & Risk       Sentiment  & Alerts
                          scoring/
                          backtest)
        │
 PostgreSQL (+RLS, partitions) · Redis (cache/queue/Streams) · Object store (S3/MinIO)
        ▲
 Celery workers + Celery Beat (ingestion · indicators · scoring · sentiment · optimization · backtests)
```

## Modules (bounded contexts)

| Module | Responsibility | Owns (tables) | Interfaces (examples) |
|--------|----------------|---------------|------------------------|
| Identity & Tenancy | users, tenants, auth, sessions, entitlements, billing sync | `tenants, users, memberships, plans, entitlements, subscriptions` | `IAuthService`, `IEntitlementService`, `ITenantContext` |
| Market Data (reference) | stock master, prices, fundamentals, ownership, corp actions; provider adapters | `stocks, daily_prices, fundamentals, shareholding, corporate_actions, index_constituents` | `IMarketDataProvider`, `IPriceRepository`, `IFundamentalsRepository` |
| Analytics | factors, normalization, scoring, backtests | `technical_indicators, factor_values, scores` | `Factor`, `Normalizer`, scoring/backtest services |
| Portfolio & Risk | portfolios, optimization, risk analytics | `portfolios, portfolio_positions, optimization_runs, risk_snapshots` | optimizer + constraints engine |
| News & Sentiment | news ingestion, sentiment scoring | `news, sentiment` | sentiment scorer |
| Notifications & Alerts | alert rules, evaluation, delivery | `alert_rules, alert_events, notifications` | alert engine |
| Platform / Core | audit, job bookkeeping, shared infra | `audit_log, jobs_runs` | tenant context, event bus |

## Runtime: one image, three roles

The **same backend image** runs `api` (FastAPI/uvicorn), `worker` (Celery), `beat` (Celery scheduler)
selected by command — domain logic stays single-sourced.

## Data architecture

See [data-models.md](./data-models.md). Key points: two domains (global vs tenant-scoped), RLS
isolation, bitemporal PIT fundamentals, partitioned price/score tables, survivorship-free history.

## API design

Contract-first: FastAPI-generated OpenAPI is the source of truth; frontend consumes a generated typed
client. REST/JSON under `/api/v1`. Standard envelope `{ success, data, error, meta }`; cursor
pagination; `Idempotency-Key` on mutations; canonical error codes. See `plans/04-api-contracts.md`.
*(No API code exists yet — see index for the to-be-generated api-contracts doc.)*

## Jobs & scheduling

Celery + Beat; all jobs idempotent & keyed (`run_key`), DAG driven by domain events, backfill = same
task different window, retry w/ backoff+jitter → dead-letter → alert. See `plans/06-scheduler-and-jobs.md`.

## Deployment

Docker (multi-stage, non-root) → docker-compose local → Kubernetes prod (HPA on api, KEDA queue-depth
autoscale on workers, singleton beat). Terraform IaC on AWS `ap-south-1`; managed Postgres/Redis/S3.
Image-based promotion local→staging→prod. See [development-guide.md](./development-guide.md) and
`plans/08-infra-devops-observability.md`. *(No IaC/CI code committed yet.)*

## Testing strategy

Unit + integration; **RLS/authz cross-tenant denial tests** and **bias-regression tests** are required
CI gates; coverage ≥80%; Playwright E2E against staging. See `plans/09` DoD.

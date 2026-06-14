# 02 — System Architecture

> Architecture style D4: **modular monolith, pre-seamed for microservice extraction.**
> Multi-tenancy D6: shared schema + `tenant_id` + Postgres RLS.

---

## 1. Guiding strategy

A funded team wants to parallelize without paying full microservices ops tax on day one. The answer is a
**modular monolith** where each module is a **bounded context** with:
- its own package, domain models, service layer, and repository;
- a **published in-process interface** (a Python Protocol/ABC) that other modules call — never reaching
  into another module's internals or tables directly;
- **no shared mutable state** across modules except through these interfaces or the event bus.

Because modules communicate only through interfaces and domain events, any module can later be lifted into
its own deployable service by swapping the in-process call for an HTTP/gRPC client and the in-process event
handler for a Redis Streams / queue consumer. This is the "seam" — see `future-scale-microservices.md`.

**Two distinct data domains** (critical to the whole design):
- **Global / reference & market data** — stocks, prices, fundamentals, news, scores. Shared by all tenants,
  **not** tenant-scoped. Read-heavy, computed by background jobs.
- **Tenant data** — users, portfolios, watchlists, screens, alerts, billing. Strictly tenant-scoped, RLS-enforced.

---

## 2. C4 — Context (level 1)

```
        ┌──────────────┐      ┌─────────────────────┐      ┌────────────────────┐
        │   End user    │──▶──│     QuantVista       │──▶──│  Market data vendor  │
        │ (browser/API) │      │      Platform        │      │ (licensed, India)   │
        └──────────────┘      │                      │──▶──│  News API (Finnhub/  │
                              │                      │      │  NewsAPI)           │
        ┌──────────────┐      │                      │──▶──│  Macro (FRED/RBI)   │
        │   Stripe      │◀────│                      │──▶──│  Email (SES/Resend) │
        │  (billing)    │      └─────────────────────┘      └────────────────────┘
        └──────────────┘
```

## 3. C4 — Containers (level 2)

```
                         ┌───────────────────────────────┐
                         │  Frontend (Next.js / TS / MUI) │
                         │  TanStack Query · Recharts      │
                         └───────────────┬────────────────┘
                                         │ HTTPS (REST /api/v1)
                         ┌───────────────▼────────────────┐
                         │   API layer (FastAPI)           │
                         │   authn/z · entitlements · rate │
                         │   limit · request validation    │
                         └───────────────┬────────────────┘
              in-process module interfaces (seams)
   ┌──────────────┬──────────────┬───────────────┬──────────────┬──────────────┐
   ▼              ▼              ▼               ▼              ▼              ▼
 Identity &    Market Data   Analytics       Portfolio      News &         Notifications
 Tenancy       (reference)   (factors,       & Risk         Sentiment      & Alerts
 module        module        scoring,        module         module         module
                             backtest)
   └──────────────┴──────────────┴───────────────┴──────────────┴──────────────┘
                                         │
                  ┌──────────────────────┼───────────────────────┐
                  ▼                      ▼                       ▼
          ┌──────────────┐      ┌────────────────┐      ┌────────────────┐
          │ PostgreSQL    │      │ Redis           │      │ Object store    │
          │ (+RLS,        │      │ cache · queue · │      │ (S3/MinIO):     │
          │ partitions)   │      │ Redis Streams   │      │ parquet, exports│
          └──────────────┘      └────────────────┘      └────────────────┘
                  ▲                      ▲
                  │                      │
          ┌───────┴──────────────────────┴────────┐
          │  Celery workers + Celery Beat          │
          │  ingestion · indicators · scoring ·    │
          │  sentiment · optimization · backtests  │
          └────────────────────────────────────────┘
```

The **same codebase** runs in three process roles: `api` (FastAPI/uvicorn), `worker` (Celery), `beat`
(Celery scheduler). This keeps domain logic single-sourced while separating runtime concerns.

---

## 4. Modules (bounded contexts) & ownership

| Module | Responsibility | Owns tables (see `03`) | Published interface (examples) |
|--------|----------------|------------------------|--------------------------------|
| **Identity & Tenancy** | Users, tenants, auth, sessions, entitlements, billing sync | `tenants, users, memberships, plans, entitlements, subscriptions` | `IAuthService`, `IEntitlementService`, `ITenantContext` |
| **Market Data (reference)** | Stock master, prices, fundamentals, ownership, corporate actions; provider adapters | `stocks, daily_prices, fundamentals, shareholding, corporate_actions` | `IMarketDataProvider`, `IPriceRepository`, `IFundamentalsRepository` |
| **News & Sentiment** | News ingestion, FinBERT sentiment, event-impact | `news, sentiment` | `INewsService`, `ISentimentService` |
| **Analytics** | Technical indicators, factors, scoring engine, backtesting | `technical_indicators, scores, factor_values, backtests` | `IScoreEngine`, `IFactor`, `IBacktestEngine` |
| **Portfolio & Risk** | Portfolios, positions, optimization, risk metrics, rebalancing | `portfolios, portfolio_positions, optimization_runs, risk_snapshots` | `IPortfolioService`, `IOptimizer`, `IRiskEngine` |
| **Notifications & Alerts** | Alert rules, evaluation, delivery, digests | `alert_rules, alert_events, notifications` | `IAlertService`, `INotificationChannel` |
| **Platform/Core** | Cross-cutting: config, logging, errors, event bus, audit | `audit_log, jobs_runs` | `IEventBus`, `IAuditLogger` |

Dependency rule (enforced by import-linter in CI): modules depend **only** on interfaces, and a strict DAG
(no cycles). Analytics depends on Market Data + News; Portfolio depends on Analytics; Alerts depends on
Analytics + Portfolio; everything may use Platform/Core. Identity is depended on by all (for tenant context)
but depends on none of the domain modules.

---

## 5. Multi-tenancy model (D6)

- **Pattern:** single database, single schema, `tenant_id UUID` on every tenant-scoped table.
- **Isolation:** PostgreSQL **Row-Level Security**. Each request sets `SET LOCAL app.tenant_id = :tid`
  inside the transaction; RLS policies (`USING (tenant_id = current_setting('app.tenant_id')::uuid)`)
  make cross-tenant reads/writes impossible even if application code has a bug.
- **Tenant context:** middleware resolves tenant from the authenticated principal and binds it to the
  request-scoped DB session. Background jobs that act on behalf of a tenant set the context explicitly;
  global data jobs run as a privileged role that bypasses RLS for reference tables only.
- **Reference/market data is NOT tenant-scoped** — it lives in tables without `tenant_id` and without RLS,
  readable by all tenants. This avoids duplicating Nifty 200 data per tenant (the common, costly mistake).
- **Noisy-neighbor control:** per-tenant rate limits & entitlement-based quotas at the API layer; heavy
  jobs (backtests, optimization) run async with per-tenant concurrency caps.
- **Upgrade path:** if a large enterprise tenant later needs hard isolation, the model supports promoting
  them to a dedicated schema/DB without affecting others (documented in `future-scale-microservices.md`).

---

## 6. Technology stack & rationale

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend framework | **FastAPI** (Python 3.12) | Async, Pydantic validation, OpenAPI out of the box |
| ORM / DB access | **SQLAlchemy 2.0** (+ Alembic migrations) | Mature, supports RLS via session events, async-capable |
| Validation/schemas | **Pydantic v2** | Boundary validation, settings management |
| Data processing | **Polars** (primary), Pandas (interop), NumPy | Polars is faster/lower-memory on the columnar workloads here |
| ML | **XGBoost / LightGBM / CatBoost**; scikit-learn | Tabular ranking/regression; transparent + strong baselines |
| NLP sentiment | **FinBERT** + Sentence-Transformers (served via a model runtime, see `05`) | Finance-tuned sentiment |
| Cache / queue / events | **Redis** (cache), **Celery** (jobs), **Redis Streams** (event bus) | Single dependency family for MVP; Streams enable later decoupling |
| Database | **PostgreSQL 16** (partitioning, RLS, JSONB) | Correctness + analytics + tenant isolation in one engine |
| Object storage | **S3** (prod) / **MinIO** (local) | Parquet history, exports, model artifacts |
| Frontend | **Next.js + React + TypeScript + MUI**; TanStack Query; Recharts | Per locked stack; SSR/ISR for SEO on public pages |
| Auth | OIDC/JWT (access+refresh); password + OAuth social; optional org SSO later | Standard, extensible |
| Billing | **Stripe** | Freemium subscriptions, webhooks → entitlement sync |
| IaC / deploy | Docker + Kubernetes; Terraform; GitHub Actions | See `08` |
| Observability | OpenTelemetry → Prometheus/Grafana; Loki or OpenSearch for logs | See `08` |

---

## 7. Cross-cutting architectural decisions

- **API-first & contract-first.** OpenAPI is the source of truth; the frontend consumes a generated typed
  client. Contracts in `04`.
- **CQRS-lite.** Reads of precomputed scores/rankings hit denormalized, cached projections; writes
  (portfolios, alerts) go through domain services. No event sourcing in v1 — overkill.
- **Event bus from day one (in-process → Redis Streams).** Domain events (`PricesIngested`,
  `ScoresComputed`, `NewsScored`, `PortfolioChanged`) decouple producers from consumers (alerts,
  cache invalidation, projections). In the monolith these can run in-process; the same handlers move to
  stream consumers on extraction.
- **Caching strategy:** Redis for hot reads (current scores, stock detail, rankings) with explicit
  invalidation on `ScoresComputed`; TTL fallback. Stale-while-revalidate on the frontend via TanStack Query.
- **Configuration:** 12-factor; env-driven `pydantic-settings`; secrets via cloud secret manager (never in
  repo). Feature flags + entitlements drive runtime capability gating.
- **Idempotency:** all ingestion and scoring jobs are idempotent and keyed (see `06`); mutating API
  endpoints accept an `Idempotency-Key` where retries are plausible (e.g., portfolio create, billing).

---

## 8. Deployment topology (v1)

- Single region (India region, e.g., `ap-south-1`), multi-AZ.
- Kubernetes deployments: `web` (Next.js), `api` (FastAPI), `worker` (Celery, autoscaled by queue depth),
  `beat` (singleton). Managed PostgreSQL (with read replica), managed Redis, object storage.
- Ingress/NGINX/ALB → API; CDN in front of frontend static/ISR assets.
- Details, scaling, and environments in `08-infra-devops-observability.md`.

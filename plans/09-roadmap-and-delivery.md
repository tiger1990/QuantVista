# 09 — Roadmap & Delivery

> Phased delivery for a **funded team (5+)** (D3). Modular monolith with explicit seams (D4) lets
> workstreams run in parallel from week one. Estimates are planning-grade, not commitments.
>
> **Ticket-ready backlog:** this roadmap is expanded sprint-by-sprint, ticket-by-ticket (QV-### with
> stories, acceptance criteria, areas, points, dependencies) under [`sprints/`](sprints/README.md).

---

## 1. Team shape & workstreams

| Workstream | Owns | Roles (indicative) |
|------------|------|--------------------|
| **Platform/Infra** | repo, CI/CD, IaC, K8s, observability, auth scaffolding | 1 platform eng |
| **Data Engineering** | provider adapters, ingestion pipeline, schema, PIT correctness, vendor integration | 1–2 data eng |
| **Quant/Analytics** | factors, scoring, optimization, backtesting, ML | 1–2 quant/ML eng |
| **Backend/API** | FastAPI, modules, entitlements, billing, tenancy | 1–2 backend eng |
| **Frontend** | Next.js app, dashboards, design system | 1–2 frontend eng |
| **Product/Design + Compliance** | PRD, UX, methodology/disclaimer content, vendor/legal | PM + designer (+ legal advisor) |

A 5–7 person team can run Platform, Data, Quant, Backend, Frontend in parallel after a shared Sprint 0.

---

## 2. Critical path & gating dependencies

```
Sprint 0 (foundations) ──▶ Data ingestion ──▶ Factors/Scoring ──▶ API+UI for scores ──▶ Portfolio ──▶ Backtest
        │                        │                                                          
        └─ Auth/Tenancy/RLS ─────┴─ Entitlements ─▶ Billing ─▶ [M-DATA: licensed vendor] ─▶ PAID LAUNCH
```

- **M-DATA (licensed India data vendor, O2)** is the hard gate for **charging money**. Free beta can run on
  dev sources; the paid launch cannot. Start vendor evaluation in Sprint 0 — procurement/legal is slow.
- **Compliance content** (methodology + disclaimer pages, T&C) gates **public launch**.

---

## 3. Phased roadmap

### Phase 0 — Foundations (Sprint 0, ~2 weeks)
- Monorepo, module skeleton + import-linter (enforce `02` dependency DAG), docker-compose, base CI.
- Postgres + Alembic + **RLS scaffolding** + seed (markets, plans, entitlements).
- Auth (register/login/JWT/refresh), tenant context middleware, `IEntitlementService` stub.
- IaC bootstrap (VPC/EKS/RDS/Redis/S3) for staging; observability baseline.
- **Begin M-DATA vendor evaluation** (decision matrix from `03`).
- **Exit:** a request can authenticate, set tenant context, and hit a health endpoint in staging; CI green.

### Phase 1 — Data backbone & Stock Intelligence (Sprints 1–3)
- `IMarketDataProvider` + first adapter (dev source); `ingest_daily_prices`, corporate actions,
  fundamentals (**bitemporal**), shareholding, index constituents (**survivorship-safe**).
- `compute_indicators` → `compute_factors`; event bus (in-process) wiring.
- **ScoreEngine** with default weights; `scores` + `factor_values` (decomposition) persisted.
- API: `/stocks`, `/scores`, `/scores/{symbol}/decomposition`, `/rankings`; caching + invalidation.
- Frontend: Dashboard (market overview, top-ranked), Stocks list, **Stock detail with score decomposition**.
- **Exit (MVP-internal):** Nifty 200 scored daily, PIT-correct, visible in UI with explainability.

### Phase 2 — Screener, News/Sentiment, Alerts (Sprints 4–5)
- Screener API + saved screens (entitlement-limited); comparison view.
- `ingest_news` → FinBERT `score_sentiment` → sentiment as scoring input; news feed UI.
- Alerts: rules, `evaluate_alerts` on `ScoresComputed`, in-app + email delivery.
- **Exit:** users can screen, read sentiment, and receive alerts.

### Phase 3 — Portfolio & Risk (Sprints 6–7)
- Portfolios/positions (tenant-scoped, RLS); **MVO + Risk Parity** optimizers; constraints engine.
- RiskEngine metrics; rebalancing suggestions; portfolio drift alerts.
- Frontend: Portfolio builder, optimization UI, risk dashboard.
- **Exit:** build → optimize → monitor a portfolio end to end.

### Phase 4 — Backtesting (Sprints 8–9)
- Async backtest engine with **bias controls + bias regression tests** (the credibility feature, `05`).
- Parquet offload for historical reads; methodology/disclaimer page.
- Frontend: backtest setup + results vs Nifty 200 TRI.
- **Exit:** reproducible, bias-controlled backtests in product.

### Phase 5 — Monetization & Launch hardening (Sprints 10–11)
- **Complete M-DATA** licensed vendor cutover (swap adapter; provenance/license_class enforced).
- Stripe billing + Checkout + webhooks → entitlement sync; Free/Pro/Quant gating live.
- Security hardening pass (ASVS L2), DPDP flows (consent, erasure), audit logging complete.
- Full observability/SLOs/alerting, backup+restore drill, load test.
- Public API (Quant, read-only subset) + docs.
- **Exit / PAID LAUNCH:** licensed data + billing + compliance content + SLOs all green.

### Phase 6 — ML augmentation (post-launch)
- XGBoost/LightGBM ranking on PIT features, walk-forward CV, champion/challenger vs factor baseline.
- Drift monitoring; ML scores surfaced as a labeled, versioned secondary signal.

---

## 4. Definition of Done (every increment)

- Tests: unit + integration; coverage ≥ 80%; **RLS/authz + bias regression tests pass** where relevant.
- Migrations expand/contract & reviewed; no destructive single-release change.
- Observability: metrics/logs/traces emitted; dashboards/alerts updated.
- Security: input validation, authz, entitlements checked; sensitive paths get `security-reviewer`.
- Docs: API/OpenAPI updated; methodology updated if scoring/backtest logic changed.
- Compliance: any research-output surface carries the disclaimer + non-advice language.

---

## 5. Risk register (top risks)

| # | Risk | Impact | Likelihood | Mitigation |
|---|------|--------|------------|------------|
| R1 | **Data licensing** blocks paid launch | High | Med | M-DATA gate; provider abstraction; start procurement Sprint 0 |
| R2 | Look-ahead/survivorship bias erodes trust | High | Med | PIT repos, historical universe, CI bias tests, published methodology |
| R3 | Data-source instability (yfinance/scrape) | Med | High | Adapters + data-quality gates + vendor migration |
| R4 | Regulatory creep into "advice" | High | Low/Med | Language discipline, disclaimers, no personalization (`07`); RIA as separate plan |
| R5 | Tenant data leakage | High | Low | RLS + authz tests CI-gated; defense in depth |
| R6 | Scope creep (US, mobile, F&O) | Med | High | Non-goals enforced; deferred to future plans |
| R7 | Optimizer instability (sample covariance) | Med | Med | Shrinkage covariance, constraints, infeasibility reporting |
| R8 | Cost overrun (compute/data) | Med | Med | Polars/Parquet, autoscaling, cost-per-tenant tracking |
| R9 | FinBERT/NLP throughput bottleneck | Low/Med | Med | Dedicated `nlp` queue/pool, batching, caching |

---

## 6. What to do first (week 1 checklist)

1. Stand up repo + module skeleton + import-linter + docker-compose + CI lint/test.
2. Postgres + Alembic + RLS scaffolding + seed (markets/plans/entitlements/Nifty 200 constituents).
3. Auth + tenant context + entitlement stub.
4. `IMarketDataProvider` interface + first dev adapter + `ingest_daily_prices` (idempotent) for a few symbols.
5. Kick off **M-DATA** vendor evaluation and the methodology/disclaimer content draft.

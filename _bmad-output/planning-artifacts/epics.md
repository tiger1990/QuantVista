# QuantVista — Epics & Stories (BMAD bridge)

> **Bridge file.** This translates the canonical backlog in `plans/sprints/` into BMAD's
> `## Epic N` / `### Story N.M` format so Sprint Planning (`[SP]`) and Create Story (`[CS]`) can parse it.
>
> - **QV-### IDs are canonical and stable** (per `plans/sprints/README.md`) — preserved in every story title.
>   The `N.M` numbering is BMAD parser plumbing only; it does **not** renumber anything.
> - **Authoritative detail (story statement, acceptance criteria, notes) lives in `plans/sprints/`.**
>   Each story points to its sprint file. Do not duplicate ACs here — read the sprint file when creating
>   the story (`[CS]`).
> - Definition of Done is inherited from `plans/09-roadmap-and-delivery.md` §4 (tests ≥80%, RLS/authz +
>   bias tests where relevant, expand/contract migrations, observability, security, research disclaimers).
> - AREA tags: `[PLAT] [DATA] [QUANT] [BE] [FE] [PROD] [SEC]`. Points: Fibonacci.

---

## Epic 1: Platform, CI/CD, IaC & Observability (EPIC-PLAT)

Foundations, pipelines, infrastructure-as-code, and operational baselines.

### Story 1.1: QV-001 — Monorepo & module skeleton with dependency linting
`[PLAT]` · 5pts · depends: — · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 1.2: QV-002 — Local dev environment (docker-compose)
`[PLAT]` · 3pts · depends: QV-001 · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 1.3: QV-003 — Base CI pipeline
`[PLAT]` · 5pts · depends: QV-001 · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 1.4: QV-008 — IaC bootstrap (AWS staging)
`[PLAT]` · 8pts · depends: — · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 1.5: QV-009 — Observability baseline
`[PLAT]` · 5pts · depends: QV-008 · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 1.6: QV-020 — Job observability dashboard
`[PLAT]` · 3pts · depends: QV-009, QV-015 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 1.7: QV-079 — Security hardening pass (OWASP ASVS L2)
`[SEC]` · 8pts · depends: QV-076 · Sprint 11 · detail: `plans/sprints/sprint-11-launch-hardening.md`

### Story 1.8: QV-082 — Observability, SLOs & alerting finalized
`[PLAT]` · 5pts · depends: QV-009 · Sprint 11 · detail: `plans/sprints/sprint-11-launch-hardening.md`

### Story 1.9: QV-083 — Backup, PITR & restore drill
`[PLAT]` · 5pts · depends: QV-008 · Sprint 11 · detail: `plans/sprints/sprint-11-launch-hardening.md`

### Story 1.10: QV-084 — Production CD pipeline + staging gates
`[PLAT]` · 5pts · depends: QV-003, QV-008 · Sprint 11 · detail: `plans/sprints/sprint-11-launch-hardening.md`

### Story 1.11: QV-085 — Load & soak test
`[PLAT]` · 3pts · depends: QV-082 · Sprint 11 · detail: `plans/sprints/sprint-11-launch-hardening.md`

---

## Epic 2: Identity, Tenancy, Entitlements & Billing (EPIC-IDN)

Auth, multi-tenancy primitives, entitlements, and Stripe billing.

### Story 2.1: QV-004 — PostgreSQL + Alembic + RLS scaffolding
`[BE]` · 8pts · depends: QV-002 · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 2.2: QV-005 — Reference seed data (markets, plans, entitlements, Nifty 200 constituents)
`[DATA]` · 3pts · depends: QV-004 · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 2.3: QV-006 — AuthN: register / login / JWT + refresh rotation
`[BE]` · 8pts · depends: QV-004 · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 2.4: QV-007 — Tenant-context middleware + Entitlement Service (stub)
`[BE]` · 5pts · depends: QV-006 · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 2.5: QV-074 — Stripe integration + checkout
`[BE]` · 8pts · depends: QV-007 · Sprint 10 · detail: `plans/sprints/sprint-10-monetization.md`

### Story 2.6: QV-075 — Stripe webhooks → entitlement sync
`[BE]` · 5pts · depends: QV-074 · Sprint 10 · detail: `plans/sprints/sprint-10-monetization.md`

### Story 2.7: QV-076 — Entitlement enforcement pass (all gated features)
`[BE]` · 5pts · depends: QV-075 · Sprint 10 · detail: `plans/sprints/sprint-10-monetization.md`

### Story 2.8: QV-077 — Public API (Quant tier, read-only) + docs
`[BE]` · 5pts · depends: QV-076 · Sprint 10 · detail: `plans/sprints/sprint-10-monetization.md`

### Story 2.9: QV-078 — Frontend: pricing, upgrade flows, billing portal
`[FE]` · 5pts · depends: QV-074, QV-076 · Sprint 10 · detail: `plans/sprints/sprint-10-monetization.md`

---

## Epic 3: Market-Data Ingestion & Correctness (EPIC-DATA)

Provider abstraction, schema, ingestion jobs, PIT/bitemporal correctness, vendor cutover.

### Story 3.1: QV-012 — IMarketDataProvider interface + dev adapter
`[DATA]` · 5pts · depends: QV-001 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 3.2: QV-013 — Schema: stocks, markets, index_constituents, corporate_actions
`[DATA]` · 5pts · depends: QV-004 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 3.3: QV-014 — Schema: daily_prices (monthly range partitions)
`[DATA]` · 5pts · depends: QV-013 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 3.4: QV-015 — Job framework: idempotency + jobs_runs + Celery/Beat wiring
`[BE]` · 5pts · depends: QV-002 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 3.5: QV-016 — ingest_daily_prices (idempotent, full universe)
`[DATA]` · 8pts · depends: QV-012, QV-014, QV-015 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 3.6: QV-017 — ingest_corporate_actions + adjusted-close computation
`[DATA]` · 5pts · depends: QV-016 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 3.7: QV-018 — Data-quality gates (post-ingestion)
`[DATA]` · 5pts · depends: QV-016 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 3.8: QV-019 — sync_stock_master + sync_index_constituents
`[DATA]` · 3pts · depends: QV-013 · Sprint 01 · detail: `plans/sprints/sprint-01-data-backbone-i.md`

### Story 3.9: QV-021 — Schema: fundamentals (bitemporal)
`[DATA]` · 8pts · depends: QV-013 · Sprint 02 · detail: `plans/sprints/sprint-02-data-backbone-ii.md`

### Story 3.10: QV-022 — ingest_fundamentals (versioned upsert)
`[DATA]` · 5pts · depends: QV-021, QV-012 · Sprint 02 · detail: `plans/sprints/sprint-02-data-backbone-ii.md`

### Story 3.11: QV-023 — Schema + ingest_shareholding (PIT ownership)
`[DATA]` · 3pts · depends: QV-013, QV-012 · Sprint 02 · detail: `plans/sprints/sprint-02-data-backbone-ii.md`

### Story 3.12: QV-024 — In-process event bus (IEventBus)
`[BE]` · 5pts · depends: QV-015 · Sprint 02 · detail: `plans/sprints/sprint-02-data-backbone-ii.md`

### Story 3.13: QV-025 — Schema: technical_indicators (partitioned) + compute_indicators
`[QUANT]` · 8pts · depends: QV-014, QV-017, QV-024 · Sprint 02 · detail: `plans/sprints/sprint-02-data-backbone-ii.md`

### Story 3.14: QV-026 — sync_macro_series (rates/inflation/GDP)
`[DATA]` · 3pts · depends: QV-015 · Sprint 02 · detail: `plans/sprints/sprint-02-data-backbone-ii.md`

### Story 3.15: QV-027 — Correction-handling pipeline test
`[QUANT]` · 3pts · depends: QV-022, QV-025 · Sprint 02 · detail: `plans/sprints/sprint-02-data-backbone-ii.md`

### Story 3.16: QV-072 — M-DATA: licensed India vendor adapter
`[DATA]` · 8pts · depends: QV-010, QV-012 · Sprint 10 · detail: `plans/sprints/sprint-10-monetization.md`

### Story 3.17: QV-073 — Production data cutover + lineage verification
`[DATA]` · 5pts · depends: QV-072 · Sprint 10 · detail: `plans/sprints/sprint-10-monetization.md`

### Story 3.18: QV-092 — Dev universe expansion to full Nifty 200 (yfinance)
`[DATA]` · 3pts · depends: QV-016, QV-019, QV-030 · added post-hoc · detail: `_bmad-output/implementation-artifacts/3-18-qv-092-dev-nifty200-universe-expansion-yfinance.md`
> Interim breadth: bring the dev universe from the 12-stock bootstrap to the full Nifty 200 via the yfinance EOD pipeline, because QV-072 (licensed vendor) is blocked (TrueData free trial is real-time-only, no historical backfill). Bundled NSE constituent snapshot + idempotent dev loader; provider `list_universe` stub untouched. Ceiling unchanged (momentum+risk only, no fundamentals/weights).

---

## Epic 4: Factors, Scoring & Intelligence (EPIC-INTEL)

Factor framework, scoring engine, stock/score APIs, frontend shell, screener.

### Story 4.1: QV-028 — Factor framework + concrete factors
`[QUANT]` · 8pts · depends: QV-025, QV-021 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.2: QV-029 — Normalizer + ScoreEngine + scores/factor_values schema
`[QUANT]` · 8pts · depends: QV-028, QV-024 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.3: QV-030 — compute_factors + compute_scores jobs
`[QUANT]` · 5pts · depends: QV-029 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.4: QV-031 — Caching + invalidation on ScoresComputed
`[BE]` · 3pts · depends: QV-030 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.5: QV-032 — API: /stocks, /stocks/{symbol}
`[BE]` · 5pts · depends: QV-031, QV-007 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.6: QV-033 — API: /scores/{symbol} + /decomposition + /rankings
`[BE]` · 5pts · depends: QV-031, QV-007 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.7: QV-034 — Frontend: app shell, auth flows, design system base
`[FE]` · 8pts · depends: QV-006 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.8: QV-035 — Frontend: Dashboard + Stocks list
`[FE]` · 5pts · depends: QV-034, QV-032, QV-033 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.9: QV-036 — Frontend: Stock detail with score decomposition
`[FE]` · 5pts · depends: QV-034, QV-033 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.10: QV-037 — Leakage/PIT regression test for scoring
`[QUANT]` · 3pts · depends: QV-030 · Sprint 03 · detail: `plans/sprints/sprint-03-stock-intelligence.md`

### Story 4.11: QV-038 — Screener query engine + API
`[BE]` · 8pts · depends: QV-033 · Sprint 04 · detail: `plans/sprints/sprint-04-screener-news.md`

### Story 4.12: QV-039 — Saved screens (entitlement-limited)
`[BE]` · 3pts · depends: QV-038, QV-007 · Sprint 04 · detail: `plans/sprints/sprint-04-screener-news.md`

### Story 4.13: QV-040 — Frontend: Screener + Comparison view
`[FE]` · 8pts · depends: QV-038, QV-036 · Sprint 04 · detail: `plans/sprints/sprint-04-screener-news.md`

### Story 4.14: QV-046 — Sentiment factor wired into scoring
`[QUANT]` · 3pts · depends: QV-044, QV-029 · Sprint 05 · detail: `plans/sprints/sprint-05-sentiment-alerts.md`

---

## Epic 5: News & Sentiment (EPIC-NEWS)

News ingestion, tagging, FinBERT sentiment, event-impact scoring.

### Story 5.1: QV-041 — INewsProvider + ingest_news (hourly)
`[DATA]` · 5pts · depends: QV-015, QV-012 · Sprint 04 · detail: `plans/sprints/sprint-04-screener-news.md`

### Story 5.2: QV-042 — News tagging to stocks
`[DATA]` · 3pts · depends: QV-041 · Sprint 04 · detail: `plans/sprints/sprint-04-screener-news.md`

### Story 5.3: QV-043 — API + Frontend: per-stock news feed
`[BE]` `[FE]` · 5pts · depends: QV-041, QV-036 · Sprint 04 · detail: `plans/sprints/sprint-04-screener-news.md`

### Story 5.4: QV-044 — FinBERT sentiment service + model runtime
`[QUANT]` · 8pts · depends: QV-041 · Sprint 05 · detail: `plans/sprints/sprint-05-sentiment-alerts.md`

### Story 5.5: QV-045 — Event-impact scorer
`[QUANT]` · 3pts · depends: QV-044 · Sprint 05 · detail: `plans/sprints/sprint-05-sentiment-alerts.md`

---

## Epic 6: Alerts & Notifications (EPIC-ALERT)

Alert rules, evaluation, deduplication, delivery, management UI.

### Story 6.1: QV-047 — Alerts schema + rule engine
`[BE]` · 5pts · depends: QV-007 · Sprint 05 · detail: `plans/sprints/sprint-05-sentiment-alerts.md`

### Story 6.2: QV-048 — evaluate_alerts + deduplication
`[BE]` · 5pts · depends: QV-047, QV-030 · Sprint 05 · detail: `plans/sprints/sprint-05-sentiment-alerts.md`

### Story 6.3: QV-049 — Notification delivery (in-app + email)
`[BE]` · 5pts · depends: QV-048 · Sprint 05 · detail: `plans/sprints/sprint-05-sentiment-alerts.md`

### Story 6.4: QV-050 — Frontend: Alerts management + notifications
`[FE]` · 5pts · depends: QV-047, QV-035 · Sprint 05 · detail: `plans/sprints/sprint-05-sentiment-alerts.md`

---

## Epic 7: Portfolio & Risk (EPIC-PORT)

Portfolio CRUD, optimizers, constraints, risk metrics, rebalancing.

### Story 7.1: QV-051 — Schema: portfolios + portfolio_positions (RLS)
`[BE]` · 5pts · depends: QV-004 · Sprint 06 · detail: `plans/sprints/sprint-06-portfolio-i.md`

### Story 7.2: QV-052 — Portfolio CRUD API
`[BE]` · 5pts · depends: QV-051, QV-007 · Sprint 06 · detail: `plans/sprints/sprint-06-portfolio-i.md`

### Story 7.3: QV-053 — Constraints engine
`[QUANT]` · 5pts · depends: — · Sprint 06 · detail: `plans/sprints/sprint-06-portfolio-i.md`

### Story 7.4: QV-054 — Mean-Variance optimizer (shrinkage covariance)
`[QUANT]` · 8pts · depends: QV-053, QV-025 · Sprint 06 · detail: `plans/sprints/sprint-06-portfolio-i.md`

### Story 7.5: QV-055 — Optimize API
`[BE]` · 3pts · depends: QV-054, QV-052 · Sprint 06 · detail: `plans/sprints/sprint-06-portfolio-i.md`

### Story 7.6: QV-056 — Frontend: Portfolio builder + optimization UI
`[FE]` · 8pts · depends: QV-052, QV-055, QV-035 · Sprint 06 · detail: `plans/sprints/sprint-06-portfolio-i.md`

### Story 7.7: QV-057 — Risk Parity optimizer
`[QUANT]` · 5pts · depends: QV-053 · Sprint 07 · detail: `plans/sprints/sprint-07-portfolio-ii-risk.md`

### Story 7.8: QV-058 — RiskEngine metrics
`[QUANT]` · 8pts · depends: QV-025, QV-051 · Sprint 07 · detail: `plans/sprints/sprint-07-portfolio-ii-risk.md`

### Story 7.9: QV-059 — Rebalancing + drift alerts
`[BE]` `[QUANT]` · 5pts · depends: QV-058, QV-048 · Sprint 07 · detail: `plans/sprints/sprint-07-portfolio-ii-risk.md`

### Story 7.10: QV-060 — Frontend: Risk dashboard + rebalancing UI
`[FE]` · 8pts · depends: QV-058, QV-059, QV-056 · Sprint 07 · detail: `plans/sprints/sprint-07-portfolio-ii-risk.md`

### Story 7.11: QV-061 — Portfolio multi-tenancy isolation tests
`[SEC]` · 3pts · depends: QV-051, QV-058 · Sprint 07 · detail: `plans/sprints/sprint-07-portfolio-ii-risk.md`

---

## Epic 8: Backtesting (EPIC-BT)

Backtest engine, PIT data access, survivorship-free universe, bias regression, metrics, UI.

### Story 8.1: QV-062 — Backtest spec + schema (async)
`[BE]` · 5pts · depends: QV-007 · Sprint 08 · detail: `plans/sprints/sprint-08-backtesting-i.md`

### Story 8.2: QV-063 — PIT data access for backtests
`[QUANT]` · 8pts · depends: QV-021, QV-030 · Sprint 08 · detail: `plans/sprints/sprint-08-backtesting-i.md`

### Story 8.3: QV-064 — Survivorship-free historical universe
`[QUANT]` · 5pts · depends: QV-019, QV-013 · Sprint 08 · detail: `plans/sprints/sprint-08-backtesting-i.md`

### Story 8.4: QV-065 — Backtest engine core (rebalance loop + frictions)
`[QUANT]` · 8pts · depends: QV-063, QV-064, QV-053 · Sprint 08 · detail: `plans/sprints/sprint-08-backtesting-i.md`

### Story 8.5: QV-066 — Bias regression test suite (CI, non-skippable)
`[QUANT]` · 5pts · depends: QV-063, QV-064 · Sprint 08 · detail: `plans/sprints/sprint-08-backtesting-i.md`

### Story 8.6: QV-067 — Parquet offload + DuckDB/Polars read path
`[DATA]` · 8pts · depends: QV-065 · Sprint 09 · detail: `plans/sprints/sprint-09-backtesting-ii.md`

### Story 8.7: QV-068 — Performance & risk metrics suite
`[QUANT]` · 5pts · depends: QV-065 · Sprint 09 · detail: `plans/sprints/sprint-09-backtesting-ii.md`

### Story 8.8: QV-069 — Reproducibility guarantee
`[QUANT]` · 3pts · depends: QV-065, QV-068 · Sprint 09 · detail: `plans/sprints/sprint-09-backtesting-ii.md`

### Story 8.9: QV-071 — Frontend: Backtest setup + results
`[FE]` · 8pts · depends: QV-062, QV-068, QV-056 · Sprint 09 · detail: `plans/sprints/sprint-09-backtesting-ii.md`

---

## Epic 9: ML Augmentation (EPIC-ML)

Feature store, training pipeline, evaluation gate, serving, drift monitoring.

### Story 9.1: QV-087 — Feature store from PIT factor_values
`[QUANT]` · 5pts · depends: QV-029 · Sprint 12 · detail: `plans/sprints/sprint-12-ml-augmentation.md`

### Story 9.2: QV-088 — Walk-forward / purged CV training pipeline
`[QUANT]` · 8pts · depends: QV-087 · Sprint 12 · detail: `plans/sprints/sprint-12-ml-augmentation.md`

### Story 9.3: QV-089 — Champion/challenger evaluation gate
`[QUANT]` · 5pts · depends: QV-088, QV-066 · Sprint 12 · detail: `plans/sprints/sprint-12-ml-augmentation.md`

### Story 9.4: QV-090 — Batch ML scoring + serving
`[BE]` `[QUANT]` · 5pts · depends: QV-089, QV-030 · Sprint 12 · detail: `plans/sprints/sprint-12-ml-augmentation.md`

### Story 9.5: QV-091 — Drift monitoring
`[QUANT]` `[PLAT]` · 3pts · depends: QV-090 · Sprint 12 · detail: `plans/sprints/sprint-12-ml-augmentation.md`

---

## Epic 10: Compliance & Data Licensing (EPIC-COMP)

Non-advice posture, methodology content, data-vendor licensing, DPDP, audit.

### Story 10.1: QV-010 — [SPIKE] M-DATA: India data-vendor evaluation
`[PROD]` · 5pts · depends: — · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 10.2: QV-011 — Compliance content draft: methodology + non-advice disclaimer
`[PROD]` · 3pts · depends: — · Sprint 00 · detail: `plans/sprints/sprint-00-foundations.md`

### Story 10.3: QV-070 — Methodology & Disclaimer page
`[PROD]` · 3pts · depends: QV-011 · Sprint 09 · detail: `plans/sprints/sprint-09-backtesting-ii.md`

### Story 10.4: QV-080 — DPDP data-subject flows (consent, access, erasure)
`[BE]` `[SEC]` · 8pts · depends: QV-076 · Sprint 11 · detail: `plans/sprints/sprint-11-launch-hardening.md`

### Story 10.5: QV-081 — Audit logging complete
`[SEC]` · 5pts · depends: QV-079 · Sprint 11 · detail: `plans/sprints/sprint-11-launch-hardening.md`

### Story 10.6: QV-086 — Launch compliance content finalized
`[PROD]` · 2pts · depends: QV-070, QV-080 · Sprint 11 · detail: `plans/sprints/sprint-11-launch-hardening.md`

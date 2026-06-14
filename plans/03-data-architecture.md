# 03 — Data Architecture

> Contains the **#1 production risk: data licensing**, the relational schema/ERD, point-in-time
> correctness, partitioning, the data-lake strategy, and caching.
>
> **Implementation:** this schema is realized as ordered Alembic migrations in
> [`../db/`](../db/README.md) (revisions `0001`→`0012`), including partitioning, bitemporal PIT columns,
> and RLS policies, plus an idempotent reference seed (`db/seeds/seed_reference.sql`).

---

## 1. Data licensing & sourcing (READ FIRST — gating for monetization, decision O2)

A paid SaaS redistributes/derives value from market data. License terms are a hard constraint, not a detail.

### Source posture by lifecycle stage

| Source | MVP / dev | Paid production | Notes |
|--------|-----------|-----------------|-------|
| **yfinance / Yahoo Finance** | ✅ allowed for internal dev only | ❌ **not licensed** for commercial use | Convenient, unreliable fields, rate-limited. Never the backbone of a paying tier. |
| **NSE/BSE official feeds** | ⚠️ public site scraping is fragile & ToS-risky | ✅ via **licensed data subscription/vendor** | Authoritative for India prices, corporate actions, shareholding. Commercial use needs a license. |
| **Financial Modeling Prep / Alpha Vantage / Finnhub** | ✅ free tiers | ✅ paid tiers (check India coverage & redistribution clause) | Good for fundamentals/ratios; verify Nifty 200 coverage depth. |
| **Macro (FRED, RBI/MOSPI)** | ✅ | ✅ | FRED is free & redistributable with attribution; RBI/MOSPI public. |
| **News (NewsAPI / Finnhub news / GDELT)** | ✅ free tiers | ✅ paid tiers | Check redistribution/display limits; we store derived sentiment, link to source. |

### India commercial data-vendor matrix (candidates for O2 / milestone M-DATA)

| Provider | Typical data | Best suited for | QuantVista fit |
|----------|-------------|-----------------|----------------|
| **NSE Data & Analytics Ltd.** | NSE historical + real-time | Direct exchange-backed sourcing | Authoritative; heavier process/cost; consider at scale |
| **BSE India Market Data Services** | BSE market data | Direct exchange-backed sourcing | Add if BSE coverage needed |
| **Global Datafeeds (GDFL)** | Real-time + historical Indian APIs | Retail / startup-friendly | **Strong Phase-2/3 candidate** — affordable, commercial licensing |
| **TrueData** | Real-time feeds, historical, options data | Quant / algorithmic trading | **Strong Phase-2/3 candidate** — quant-oriented, startup-friendly |
| **Refinitiv (LSEG)** | Institutional global + Indian data | Enterprise platforms | Overkill/expensive for v1; revisit if enterprise tenants demand it |
| **Bloomberg** | Premium institutional | Large financial firms | Out of scope for v1 economics |
| **FactSet** | Fundamentals, estimates, market data | Professional research platforms | Out of scope for v1 economics |

**Practical recommendation:** for a quant screener/research SaaS targeting Indian retail, start commercial
licensing with **TrueData or Global Datafeeds** — materially more affordable and startup-friendly than
Bloomberg/FactSet/Refinitiv while still offering commercial terms. Reserve direct NSE/BSE or
Refinitiv-class feeds for when scale or enterprise customers justify the cost/process.

### Phased licensing progression (maps to roadmap `09`)

| Phase | Stage | Data posture |
|-------|-------|--------------|
| **1 — MVP (internal)** | Pre-users | yfinance / Yahoo Finance, NSE public disclosures, company annual reports — **internal dev only, never a paying tier** |
| **2 — Pilot users** | Free beta | **Global Datafeeds or TrueData**; licensed historical EOD data; basic compliance review |
| **3 — Commercial SaaS** | Paid launch | Exchange-authorized data; **display + redistribution rights**; formal customer agreements; auditable data lineage |

> **Display & redistribution rights matter as much as API quality.** If we display live prices, charts, or
> signals derived from exchange data, raw data access is *not enough* — we may need explicit **display and
> redistribution permissions**. Legal terms are a first-class selection criterion, not an afterthought. The
> `license_class` field (below) and our provenance tracking exist precisely to make "can we redistribute
> this?" answerable per datum.

### Rules baked into the architecture
1. **Provider abstraction:** all external data enters through `IMarketDataProvider` / `INewsProvider`
   adapters. Swapping vendors = new adapter, zero analytics changes — this is *why* O2 can be deferred to
   M-DATA without blocking design or build.
2. **Provenance tracking:** every ingested datum records `source`, `source_url`, `ingested_at`,
   `as_of_date`, and `license_class` (incl. whether display/redistribution is permitted). Enables audit,
   dispute resolution, **auditable data lineage** (Phase-3 requirement), and "can we redistribute this?".
3. **Monetization gate:** the Free/Pro/Quant tiers **must not** be served from a non-commercial source.
   Securing a commercially licensed India vendor with display/redistribution rights (O2) is a prerequisite
   milestone (M-DATA) before charging (see `09`).
4. **Store derived, link to original** for news (avoid re-hosting full copyrighted articles).

> **Action item carried to roadmap:** vendor evaluation + contract is a named milestone (M-DATA) blocking
> the billing launch. Start in Sprint 0 — procurement, legal review, and redistribution-rights negotiation
> are slow. (O2 decision can finalize close to launch; the *process* must start early.)

---

## 2. Data domains (recap from `02`)

- **Global reference/market data** — no `tenant_id`, no RLS, shared by all tenants, written only by jobs.
- **Tenant data** — `tenant_id` on every row, RLS-enforced, written by user actions.

This split is the backbone of the schema below.

---

## 3. Logical data model (ERD overview)

```
GLOBAL (no tenant_id)                          TENANT-SCOPED (tenant_id + RLS)
────────────────────                           ──────────────────────────────
markets ──< stocks ──< daily_prices            tenants ──< memberships >── users
                  │  ──< fundamentals (PIT)     tenants ──< subscriptions ──> plans
                  │  ──< shareholding (PIT)      plans   ──< entitlements
                  │  ──< corporate_actions       tenants ──< portfolios ──< portfolio_positions
                  │  ──< technical_indicators    tenants ──< watchlists ──< watchlist_items
                  │  ──< factor_values           tenants ──< saved_screens
                  │  ──< scores                  tenants ──< alert_rules ──< alert_events
                  │  ──< news ──< sentiment      tenants ──< backtests
                  └──< macro_series              tenants ──< notifications
                                                 (global) audit_log, jobs_runs
```

---

## 4. Core tables (selected DDL-level detail)

> Conventions: UUID PKs for entities (`gen_random_uuid()`), `BIGSERIAL` for high-volume append tables,
> `created_at/updated_at TIMESTAMPTZ`, soft-delete via `deleted_at` only where user-facing. All timestamps
> UTC; display converts to IST. Money/ratios as `NUMERIC`, never float.

### 4.1 Reference & market (global)

**markets** — supports market-agnostic core (D2).
`id, code ('NSE'), name, country, currency, timezone, trading_calendar_ref, is_active`

**stocks**
`id UUID PK, market_id FK, symbol, isin, company_name, sector, industry, market_cap_bucket,
listed_on DATE, delisted_on DATE NULL, is_active BOOL, created_at, updated_at`
- `delisted_on` is **mandatory for survivorship-bias-free history** — delisted constituents stay queryable.
- Unique `(market_id, symbol)`; index `isin`.

**index_constituents** — point-in-time index membership (so backtests use the *historical* Nifty 200).
`id, index_code ('NIFTY200'), stock_id FK, effective_from DATE, effective_to DATE NULL, weight NUMERIC`

**daily_prices** — append-only, **partitioned by month on `date`** (range partition).
`id BIGSERIAL, stock_id FK, date DATE, open, high, low, close, adj_close, volume,
source, ingested_at` — unique `(stock_id, date)`; BRIN index on `date`, btree `(stock_id, date)`.

**fundamentals** — **bitemporal / PIT** (see §5).
`id, stock_id FK, period_end DATE, statement_type, pe, forward_pe, pb, roe, roce, debt_equity,
revenue, revenue_growth, eps, eps_growth, fcf, operating_margin, net_margin, current_ratio,
quick_ratio, ev_ebitda, peg, price_sales, enterprise_value, reported_at TIMESTAMPTZ,
knowledge_from TIMESTAMPTZ, knowledge_to TIMESTAMPTZ NULL, source, ingested_at`

**shareholding** — PIT ownership.
`id, stock_id FK, as_of_date DATE, promoter_holding, fii_holding, dii_holding, public_holding,
pledged_pct, source` — unique `(stock_id, as_of_date)`.

**corporate_actions** — splits, bonuses, dividends (needed to compute `adj_close` correctly).
`id, stock_id FK, ex_date DATE, action_type, ratio_or_amount, details JSONB, source`

**technical_indicators** — derived, partitioned by month.
`id BIGSERIAL, stock_id FK, date DATE, sma_50, sma_200, ema_20, rsi_14, macd, macd_signal,
bollinger_upper, bollinger_lower, atr_14, ret_3m, ret_6m, ret_12m, vol_30d, beta_1y`

**factor_values** — normalized per-factor inputs feeding the score (explainability source of truth).
`id BIGSERIAL, stock_id FK, date DATE, factor_key, raw_value, zscore, percentile_sector,
percentile_universe`

**scores** — daily composite + sub-scores.
`id BIGSERIAL, stock_id FK, date DATE, fundamental_score, momentum_score, quality_score,
sentiment_score, risk_score, composite_score, weights_version, model_version`
- unique `(stock_id, date)`; this is the primary read-hot table → cached aggressively.

**news**
`id, stock_id FK NULL, headline, summary, source, source_url, published_at, language, raw_ref (object key), ingested_at`

**sentiment**
`id, news_id FK, label, score NUMERIC, confidence NUMERIC, impact_score, model_version`

**macro_series** — generic time series (rates, inflation, GDP).
`id, series_code, date DATE, value NUMERIC, source`

### 4.2 Identity, tenancy, billing (tenant-scoped except plans)

**tenants** `id UUID PK, name, type ('individual'|'org'), status, created_at`
**users** `id UUID PK, email UNIQUE, password_hash, name, status, mfa_enabled, last_login_at`
**memberships** `id, tenant_id FK, user_id FK, role ('owner'|'admin'|'member'), created_at`
**plans** (global) `id, code ('free'|'pro'|'quant'), name, price_inr, billing_interval, is_active`
**entitlements** (global) `id, plan_id FK, key ('max_portfolios'|'backtest'|'api_access'|...), limit_int, flag_bool`
**subscriptions** `id, tenant_id FK, plan_id FK, stripe_subscription_id, status, current_period_end`

### 4.3 User application data (tenant-scoped, RLS)

**portfolios** `id, tenant_id, user_id, name, benchmark ('NIFTY200_TRI'), base_currency, created_at`
**portfolio_positions** `id, tenant_id, portfolio_id FK, stock_id FK, weight NUMERIC, target_weight, shares, avg_cost`
**watchlists / watchlist_items** — tenant-scoped lists of `stock_id`.
**saved_screens** `id, tenant_id, user_id, name, criteria JSONB, created_at`
**alert_rules** `id, tenant_id, user_id, scope ('stock'|'portfolio'), target_id, condition JSONB, channel, is_active`
**alert_events** `id, tenant_id, alert_rule_id FK, fired_at, payload JSONB, delivered_at, status`
**backtests** `id, tenant_id, user_id, spec JSONB, status, started_at, finished_at, result_ref (object key), metrics JSONB`
**notifications** `id, tenant_id, user_id, type, payload JSONB, read_at, created_at`

### 4.4 Platform (global)

**audit_log** `id BIGSERIAL, actor_user_id, tenant_id NULL, action, entity, entity_id, before JSONB, after JSONB, ip, created_at`
**jobs_runs** `id, job_name, run_key, status, started_at, finished_at, rows_in, rows_out, error, metadata JSONB`

---

## 5. Point-in-time correctness (core to credibility)

Financial data is **revised** (restatements, late filings, index reconstitution). Naively overwriting it
silently injects look-ahead bias into scores and backtests. QuantVista treats correctness as a first-class
concern:

- **Bitemporal fundamentals:** `period_end` (what period the data describes) + `knowledge_from/knowledge_to`
  (when we knew it). A score for date `D` reads the row where `knowledge_from <= D < knowledge_to`. Revisions
  insert a new version and close the prior `knowledge_to`; nothing is destructively updated.
- **Survivorship-bias-free universe:** `stocks.delisted_on` + `index_constituents` give the *historical*
  Nifty 200 membership and weights. Backtests iterate the universe **as it was**, including delisted names.
- **Adjusted prices computed, not trusted blindly:** `adj_close` derived from `corporate_actions` so splits/
  bonuses don't fake momentum. Raw `close` retained.
- **As-of querying:** repositories expose `as_of(date)` query methods; the scoring/backtest engines must use
  them — enforced by code review + tests (see `05` bias tests).

---

## 6. Partitioning, indexing, retention

- **Partition** `daily_prices`, `technical_indicators`, `factor_values`, `scores` by **monthly range on
  `date`**. Detach/archive old partitions to Parquet (see §7) per retention policy.
- **Indexes:** btree `(stock_id, date DESC)` for time-series reads; BRIN on `date` for scans; partial index
  `WHERE is_active` on `stocks`; GIN on JSONB criteria/specs where queried.
- **Retention:** hot in Postgres (e.g., 3–5y prices, full scores); colder history offloaded to Parquet/object
  store. Tenant data retained per policy + DPDP deletion requests (see `07`).

---

## 7. Data-lake / analytics strategy (phased)

- **Phase 1:** PostgreSQL is the system of record and analytics store. Sufficient for Nifty 200 (≈200 symbols).
- **Phase 2+:** offload historical partitions to **Parquet on S3/MinIO**, path-partitioned
  `/{market}/{table}/{year}/{month}/`. Use Polars/DuckDB for heavy backtests reading Parquet directly —
  far faster and cheaper than scanning Postgres for multi-year, multi-factor sweeps.
- Model artifacts (XGBoost/LightGBM, FinBERT fine-tunes) versioned in object store with a model registry
  pointer (`scores.model_version`).
- Keep a **content-hash cache** for expensive derived computations keyed by input data hash, so re-runs over
  unchanged inputs are skipped.

---

## 8. Caching

| Cache | Keyed by | Invalidation |
|-------|----------|--------------|
| Current scores / rankings | `score:{market}:{date}` , `rank:{universe}:{date}` | on `ScoresComputed` event; TTL backstop |
| Stock detail snapshot | `stock:{id}:detail` | on price/fundamentals/score change for the stock |
| Screener results | hash of criteria | short TTL (e.g., 5 min) + event invalidation |
| Entitlements | `ent:{tenant_id}` | on subscription change (Stripe webhook) |

Frontend layers stale-while-revalidate via TanStack Query on top of these.

---

## 9. Migrations & schema governance

- **Alembic** migrations, reviewed in PRs; forward-only in prod with expand/contract for zero-downtime
  (add nullable → backfill → enforce → drop old) — see `database-migrations` practices.
- RLS policies are part of migrations and covered by tests that assert cross-tenant access is denied.
- Seed/reference data (markets, plans, entitlements, Nifty 200 constituents) loaded via versioned seed
  scripts, idempotent.

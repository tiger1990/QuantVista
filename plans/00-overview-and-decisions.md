# 00 — Overview & Decisions

> **Document owner:** Principal Architect / Product
> **Status:** Baseline v1.0
> **Last updated:** 2026-06-14

---

## 1. Executive summary

**QuantVista** is a multi-tenant SaaS that continuously analyzes the **Nifty 200** universe and produces
institutional-style intelligence: factor-based **scores** (fundamental, momentum, quality, sentiment, risk),
a composite **research signal**, **portfolio construction & optimization**, **risk analytics**, **news/sentiment
intelligence**, and **backtesting**.

The product is deliberately positioned as a **research & analytics tool**, not a registered investment
advisor. All outputs are framed as research signals with non-advice disclaimers (see
`07-security-and-compliance.md`). A regulated-advisory evolution is captured separately in
`future-ria-compliance.md`.

The system starts as a **modular monolith with explicit, pre-seamed service boundaries** so a funded team
can parallelize immediately and extract microservices when scale demands it — without a rewrite.

### Why this is more than a stock screener
A screener filters on raw fields. QuantVista maintains **point-in-time correct** market, fundamental,
ownership, and news data; computes a transparent, weighted **multi-factor score** per stock per day; and
turns rankings into **optimized portfolios** with explicit risk constraints and **bias-controlled
backtests**. That is the difference between a toy and a research platform credible to analysts and quants.

---

## 2. Locked decisions (Decision Log)

These are the load-bearing decisions agreed before any code. Changing one is a re-plan event, not a tweak.

| ID | Decision | Choice | Rationale | Reversibility |
|----|----------|--------|-----------|---------------|
| D1 | **Regulatory posture (v1)** | Research/analytics tool; no personalized advice | Avoids SEBI/SEC RIA registration while validating; standard posture for screeners/quant tools | Low — pivoting to advisory is a major program (`future-ria-compliance.md`) |
| D2 | **Initial market** | India first — **Nifty 200** | Home-market knowledge; build market-agnostic abstractions day one | Medium — US is additive, not a rewrite (`future-us-market-expansion.md`) |
| D3 | **Build context** | Funded team (5+) | Plan explicit service boundaries & parallel workstreams upfront | n/a |
| D4 | **Architecture style** | Modular monolith, pre-seamed for extraction | Lower ops cost now, microservices later without rewrite (`future-scale-microservices.md`) | High — seams make extraction cheap |
| D5 | **Monetization** | Freemium SaaS tiers (Free / Pro / Quant) | Growth funnel + upsell; design multi-tenancy, entitlements, billing from day one | Medium — tiers/pricing tunable; tenancy is structural |
| D6 | **Multi-tenancy model** | Shared DB, shared schema, `tenant_id` + Postgres **Row-Level Security** | Cost-efficient at SaaS scale; strong isolation via RLS; market/reference data is global, user data is tenant-scoped | Medium |
| D7 | **Primary language/stack** | Python 3.12 + FastAPI backend; Next.js/TypeScript frontend; PostgreSQL + Redis + Celery | Best-in-class for quant/data + production web; matches team skill assumptions | Low |
| D8 | **Cloud target** | **AWS** (was O1) | Broadest managed-service maturity + India region (`ap-south-1`); **Terraform IaC keeps it portable** so the choice is a preference, not a lock-in | Medium — IaC abstracts most of it |

### Decisions still open (tracked, non-blocking — abstracted behind interfaces, do not block design/build)
| ID | Open question | Needed by | Why it's safe to defer |
|----|---------------|-----------|------------------------|
| O2 | Production India market-data vendor & commercial terms | **Before paid launch only** (milestone M-DATA) | All external data enters via `IMarketDataProvider`; final provider/contract can be chosen close to launch without touching analytics. Candidate matrix + phased progression in `03` §1. |
| O3 | Exact freemium limits & price points | Before billing sprint | Limits/flags live behind the Entitlement Service; pricing can be finalized after product validation & user feedback without structural change. |

> **Resolution note (2026-06-14):** O1 resolved to AWS (now D8). O2 and O3 remain intentionally deferred —
> both are abstracted behind clean interfaces, so development and system design proceed without them. Only
> D8 influences some infra-specific implementation detail (`08`).

---

## 3. The single biggest risk: data licensing

For a **paid** SaaS, market data is a legal product input, not a free utility.
- **Yahoo Finance** and unofficial scrapers: fine for personal MVP, **not** licensed for commercial
  redistribution. They must not back a paying tier.
- **NSE/BSE** data for commercial use generally requires a licensed data vendor or an exchange data
  subscription.
- **Action:** treat vendor selection & licensing (O2) as a **gating dependency** for monetization. The
  architecture isolates the data source behind a provider interface so the vendor can be swapped without
  touching analytics. Details and a vendor decision matrix live in `03-data-architecture.md`.

This risk is called out again wherever relevant. Do not let MVP convenience (Yahoo/yfinance) silently
become the production data backbone.

---

## 4. Product principles (non-negotiable)

1. **Research, not advice.** Every recommendation-shaped output is a "research signal" with a disclaimer
   and a transparent, inspectable derivation. No "you should buy X."
2. **Point-in-time correctness.** Scores and backtests use only data that was knowable at the time.
   No look-ahead bias, no survivorship bias. (See `05`.)
3. **Explainability over black-box.** Every score decomposes into its factor contributions. ML augments,
   it does not replace, the transparent factor model.
4. **Tenant isolation by construction.** Enforced at the database (RLS), not just the application layer.
5. **Idempotent, replayable pipelines.** Financial data gets revised; ingestion must be re-runnable and
   correcting, never duplicating.
6. **Market-agnostic core.** India-specific logic lives behind abstractions; adding the US is configuration
   + adapters, not a fork.

---

## 5. Glossary

| Term | Meaning |
|------|---------|
| **Factor** | A measurable attribute that explains return/risk (e.g., value, momentum, quality). |
| **Composite score** | Weighted blend of factor scores → a single 0–100 research signal per stock. |
| **Point-in-time (PIT)** | Data as it was known on a given date, including later corrections tracked bitemporally. |
| **Survivorship bias** | Error from analyzing only stocks that still exist, ignoring delisted ones. |
| **Look-ahead bias** | Using information in a backtest that was not available at decision time. |
| **MVO** | Mean-Variance Optimization (Markowitz portfolio construction). |
| **HRP** | Hierarchical Risk Parity portfolio construction. |
| **RLS** | PostgreSQL Row-Level Security — per-row tenant access enforcement. |
| **Entitlement** | A capability/limit granted to a tenant by their plan (e.g., max portfolios). |
| **Tenant** | A billing/account boundary (an individual or organization) owning users and portfolios. |

---

## 6. Change log

| Date | Author | Change |
|------|--------|--------|
| 2026-06-14 | Architecture | Baseline v1.0 created from `plan_discussion.txt` + locked decisions D1–D7. |
| 2026-06-14 | Architecture | O1 resolved → **D8: AWS** (IaC-portable). O2/O3 confirmed deferred behind interfaces. Added India data-vendor matrix + phased licensing progression to `03` §1. |

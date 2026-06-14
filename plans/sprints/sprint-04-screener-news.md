# Sprint 04 — Screener + News Ingestion

**Phase:** 2 · **Goal:** a powerful screener with saved screens + comparison, and the news ingestion pipeline.
**Exit gate:** users can screen the universe, save screens (entitlement-limited), compare stocks, and see a
per-stock news feed.

> See `../04-api-contracts.md` §3.4, `../01-prd.md` Pillars B/C, `../06` news jobs.

---

### QV-038 — Screener query engine + API `[BE]` · `8pts` · Epic: EPIC-INTEL · depends: QV-033
**Story:** As a user, I want to filter/sort the universe by any factor/fundamental, so I find candidates fast.
**Acceptance criteria:**
- `POST /screener` accepts validated filter specs against an **allow-list** of fields/operators (no injection);
  sort + cursor pagination; returns `meta.count`.
- Full-universe query returns < 1s (US-01 AC); served from cached projections where possible.
**Notes:** `04` §3.4; JSONB criteria validated (`07` §4).

### QV-039 — Saved screens (entitlement-limited) `[BE]` · `3pts` · Epic: EPIC-INTEL · depends: QV-038, QV-007
**Story:** As a user, I want to save screens, so I reuse them.
**Acceptance criteria:**
- `saved_screens` (tenant-scoped, RLS); create/list/delete; enforce per-tier limit → `entitlement_exceeded`
  (US-06).
**Notes:** `01` §4 limits.

### QV-040 — Frontend: Screener + Comparison view `[FE]` · `8pts` · Epic: EPIC-INTEL · depends: QV-038, QV-036
**Story:** As a user, I want an interactive screener and side-by-side comparison, so I analyze efficiently.
**Acceptance criteria:**
- Screener UI with shareable URL state, saved-screen management, upgrade CTA on limit; compare up to N stocks
  across factors/fundamentals.
**Notes:** `01` US-01.

### QV-041 — `INewsProvider` + `ingest_news` (hourly) `[DATA]` · `5pts` · Epic: EPIC-NEWS · depends: QV-015, QV-012
**Story:** As the platform, I want stock-tagged news ingested hourly, so sentiment has input.
**Acceptance criteria:**
- `INewsProvider` adapter (NewsAPI/Finnhub free tier); `news` table stores headline/summary/source/url/
  published_at; **store derived, link to original** (no full re-hosting); emits `NewsIngested`.
- Dedup on source URL; idempotent per window.
**Notes:** `03` §1 rule 4; `06` job catalog.

### QV-042 — News tagging to stocks `[DATA]` · `3pts` · Epic: EPIC-NEWS · depends: QV-041
**Story:** As the platform, I want news linked to the right stock, so feeds are relevant.
**Acceptance criteria:**
- Map articles to `stock_id` via symbol/ISIN/company-name matching; unmatched stored with `stock_id=NULL`.
**Notes:** Precision over recall; ambiguous matches flagged.

### QV-043 — API + Frontend: per-stock news feed `[BE]` `[FE]` · `5pts` · Epic: EPIC-NEWS · depends: QV-041, QV-036
**Story:** As a user, I want recent news on a stock, so I have context.
**Acceptance criteria:**
- `GET /stocks/{symbol}/news` (history window per entitlement: Free 7d / Pro 1y / Quant full); news section on
  stock detail; sanitized rendering, links out.
**Notes:** `01` §4; XSS-safe (`07` §4).

**Sprint total:** ~40 pts · **Dependency note:** sentiment (Sprint 05) consumes `news`.

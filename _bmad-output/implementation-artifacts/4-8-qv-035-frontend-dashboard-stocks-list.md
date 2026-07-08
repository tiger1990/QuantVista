---
baseline_commit: 00d331068d6378b9fa96f0645e3b03f40ebdd5da
---

# Story 4.8: QV-035 — Frontend: Dashboard + Stocks list

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **a market overview and a ranked, filterable stocks list**,
so that **I see value immediately and can explore the universe**.

> Canonical ID **QV-035** · Epic 4 (EPIC-INTEL) · `[FE]` · 5pts · Sprint 03 · depends: **QV-034 ✅** (shell), **QV-032 ✅** (`/stocks`), **QV-033 ✅** (`/rankings`,`/scores`)
> Authoritative: `04` §3.2 (`/stocks` cursor + filter/sort), §3.3 (`/rankings`) · `01` Pillar A/B · Web design-quality rules (Swiss + purposeful **bento**; **no template look**). Builds on QV-034's design system.

## Data reality (checked live on the dev DB)

- **`/stocks` has data** — the seeded NIFTY 200 reference stocks (AXISBANK, BHARTIARTL, HDFCBANK, …). The list will populate.
- **`/rankings` is empty** (`as_of: null`) — **no scores are persisted.** So the dashboard's ranking + heatmap need the **scoring pipeline run** first. Hence the dev backfill (Task 5). **Honest ceiling:** dev prices (yfinance) yield **partial-coverage** scores (momentum + risk; no fundamentals until the licensed vendor, QV-072).

## Locked decisions (owner-presented)

- **Dashboard = purposeful bento** (design-quality rules) with real hierarchy: (1) a wide **market-overview** strip — avg composite, coverage %, # scored, `as_of`; (2) a **top-ranked** tile (top N from `/rankings`); (3) a **sector heatmap** tile — sectors as grid tiles colored on the oklch **positive→negative** scale by avg composite. Every tile has a **designed empty state** (dev scores may be sparse). **Not** a uniform card grid.
- **Stocks list = TanStack Table** over `/stocks`: columns `symbol · company · sector · composite`. **Cursor pagination** — "Load more" consuming `meta.next_cursor` (the API is **keyset**, not offset; no page numbers). **URL-shareable state** — `sector` filter + `sort` in `useSearchParams` (native, no `nuqs`); URL is the source of truth, drives the query key.
- **Charts:** sector heatmap = **CSS-grid tiles** (lightweight, Swiss), not a chart lib. **Recharts is deferred** to time-series (price/score history) in a later story — no charts this story beyond the heatmap.
- **Server state = TanStack Query** hooks over the **typed** client (`api.GET`): `useRankings`, `useStocks(params)`, `useDashboard`. URL params live in the query key (stale-while-revalidate). Client/URL state only; no duplication of server data.
- **Disclaimer** visible on every data surface (reuse the pattern; the API also sets the header).
- **Data population = a committed dev tool** `backend/scripts/dev_backfill.py`: for the NSE universe, ingest prices (yfinance) → persist indicators → `compute_factors` → `compute_scores`, so `/rankings` + the dashboard render real numbers. Repeatable, dev-only, documented. **No production/backend-contract change** (uses existing services/jobs).
- **Scope:** dashboard + stocks list only. **Not** this story: stock **detail** page, screener, portfolio, news, price/score charts, real-time.

## Acceptance Criteria

1. **Dashboard** (`/` overview replaced): market-overview strip (avg composite, coverage %, # scored, `as_of`), a top-ranked tile (from `/rankings`), and a **sector heatmap** — bento layout with hierarchy + per-tile empty states; visible disclaimer.
2. **Stocks list** (`/stocks`): TanStack Table (symbol/company/sector/composite) over the live `/stocks` API; **sector filter + sort** reflected in the **URL** (shareable/refresh-safe); **"Load more"** cursor pagination via `meta.next_cursor`; loading + empty states; visible disclaimer.
3. **Rankings** (`/rankings`): the composite-desc leaderboard as a TanStack Table (rank/symbol/composite/coverage), entitlement note surfaced from `meta`; empty state; disclaimer.
4. **Data fetching** via TanStack Query hooks over the **typed** client; URL params drive query keys; no server-state duplication.
5. **Dev data populated:** `scripts/dev_backfill.py` runs the NSE pipeline (ingest→indicators→factors→scores); after running it, `/rankings` returns rows and the dashboard shows real (partial-coverage) numbers. Script committed + documented; **honest coverage caveat** noted.
6. **Gates:** FE `npm run lint` + `tsc --noEmit` + `npm test` (new unit tests for the table columns / heatmap color / cursor accumulation) + `npm run build` green. Backend gates unaffected (script is dev-only, but must `ruff`/`mypy` clean). Live smoke: dashboard + stocks list render real data.

## Tasks / Subtasks

- [x] **Task 1 — data hooks** (AC: #4)
  - [x] `src/features/*/api.ts` (or `src/lib/api/queries.ts`): `useStocks({ sector, sort, cursor })`, `useRankings({ market })`, `useDashboard()` — TanStack Query over `api.GET`; typed rows from the generated schema; URL params in query keys.
- [x] **Task 2 — stocks list + rankings tables** (AC: #2, #3)
  - [x] Install `@tanstack/react-table`. A reusable `DataTable` (shadcn `<Table>` + TanStack Table). `/stocks` page: columns, URL-driven `sector`/`sort` (useSearchParams), "Load more" (accumulate cursor pages). `/rankings` page: leaderboard table + `meta` entitlement note. Loading/empty states + disclaimer.
- [x] **Task 3 — dashboard bento** (AC: #1)
  - [x] Replace the overview: `MarketOverview` strip, `TopRanked` tile, `SectorHeatmap` (CSS-grid tiles colored by avg composite on the positive→negative tokens). Hierarchy + empty states + disclaimer. Derive dashboard aggregates from `/rankings` + `/stocks` (or a small client-side rollup).
- [x] **Task 4 — unit tests** (AC: #6)
  - [x] Vitest: heatmap color-bucket function (score→token), cursor-accumulation reducer, a table-columns render (RTL) with mocked query. Keep the CI `npm test` green.
- [x] **Task 5 — dev backfill + populate** (AC: #5)
  - [x] `backend/scripts/dev_backfill.py` (ruff/mypy clean): ingest NSE prices (yfinance adapter) → persist indicators → `compute_factors` → `compute_scores`. Run it against the dev DB; confirm `/rankings` returns rows. Document usage + the partial-coverage caveat in the script + pending-verifications.
- [x] **Task 6 — gates + live smoke + reconcile** (AC: #6)
  - [x] FE lint/tsc/test/build green. Start uvicorn + `next dev`; verify the dashboard + stocks list render real data. Reconcile QV-034 → done (already applied).

## Dev Notes

### Reuse / seams
- **Typed client** (`@/lib/api/client`, `schema.d.ts`) — `api.GET("/api/v1/stocks", { params: { query: {...} } })`, `/rankings`, `/scores/{symbol}`. Rows typed via `components["schemas"]["StockListItem"]` / `RankingItem`.
- **Design system** (QV-034): tokens, shadcn primitives, `cn`, `AppNav`, disclaimer pattern, `positive`/`negative` color tokens for the heatmap.
- **Pipeline (backfill):** `market_data/services.py` `ingest` (+ `adapters/yfinance_dev.py`), `market_data/indicators.py:compute_indicators_for_date`, `jobs/scoring.py:compute_factors/compute_scores` (run_job framework). Mirror the earlier real-data smoke (ingest→indicators→factors→scores for the NSE universe).

### `/stocks` contract (04 §3.2)
`GET /stocks?market=NSE&sector=IT&filter[market_cap_bucket]=large&limit=50&cursor=…` → `StockListItem[]` (`symbol, company_name, sector, composite_score, as_of`) + `meta.next_cursor`. Sort e.g. `-momentum_score`. Cursor is opaque (keyset).

### Design-quality guardrails
Bento with hierarchy (a dominant overview strip, secondary tiles), intentional rhythm, hairline surfaces, tabular numerals for scores, semantic color (positive/negative), designed hover/empty/loading states. Light default; dark equally considered. Cite ≥4 required qualities in the Dev Agent Record.

### Boundaries
FE = client of FastAPI (no business logic; aggregates for a page are thin client rollups). The backfill is a **dev tool** — not wired to prod, not a contract change. **Not this story:** stock detail, screener, portfolio, news, charts (Recharts), real-time.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Dev backfill run** (real yfinance): 12 stocks / 3300 price rows → 12 indicators → 60 factor values →
  **12 scores** for 2026-07-07. DB confirms **avg composite 50.0, avg coverage 0.50** — the honest
  partial-coverage ceiling (momentum + risk; no fundamentals). Backend full suite + mypy still green
  (`scripts/` is outside mypy scope; the script is ruff-clean).
- **FE gates:** `npm run lint` ✓, `tsc --noEmit` ✓, **`npm test` 16 passed** (6 files), `npm run build` ✓
  (all routes prerender). CI runs the same.
- **Live proof (uvicorn + next dev + BFF):** `/rankings` returns real scores (ICICIBANK 75.3, SBIN 65.2,
  INFY 62.4; `tier_limit=50`). **Playwright E2E — 2 passed** in Chromium, incl. *"dashboard + stocks +
  rankings render live data"* (market-overview + top-ranked visible, HDFCBANK in the stocks table,
  rankings leaderboard + Free-tier note). **The dashboard shows data.**
- **tsc friction fixed:** the envelope `meta` is a loose dict → `meta.next_cursor` is `unknown`, which
  broke `useInfiniteQuery`'s `TPageParam`/`TData` inference; narrowed the cursor (`as string | null`) and
  used a `string | null` page param. Suppressed a known false-positive `react-hooks/incompatible-library`
  warning on `useReactTable`.

### Completion Notes List

- **The data is now visible** — dashboard, stocks list, and rankings all render live API data.
- **Dashboard = purposeful bento** (`page.tsx` + `components/dashboard.tsx`): a hero **MarketOverview** KPI
  strip (avg composite / coverage / # scored / as-of) spanning full width, then a 2-col row of **TopRanked**
  + **SectorHeatmap** (CSS-grid tiles colored on the `positive`/`negative` tokens by sector avg). Real
  hierarchy, per-tile empty states — not a uniform grid. Design qualities met: **scale hierarchy, spacing
  rhythm, semantic color, tabular numerals, designed empty/hover states** (≥4).
- **Stocks list** (`stocks/page.tsx`): TanStack Table over `/stocks`; **sector filter + sort URL-persisted**
  via `useSearchParams` (Suspense-wrapped); server-side sector filter drives the query, client-side column
  sort (the `/stocks` API has no server sort — QV-032 is keyset-by-symbol); **"Load more"** via
  `useInfiniteQuery` + `meta.next_cursor`; sector chips derived from the cached unfiltered query.
- **Rankings** (`rankings/page.tsx`): composite-desc leaderboard table + the `tier_limit` entitlement note
  from `meta`.
- **Reusable pieces:** `DataTable` (shadcn `<Table>` + TanStack Table, optional controlled sorting),
  `lib/score.ts` (`scoreTone`/`formatScore`/`toneTextClass` — pure, unit-tested), `Disclaimer`, typed
  query hooks (`lib/api/queries.ts`).
- **Data population:** `backend/scripts/dev_backfill.py` — a committed, repeatable **dev tool** running the
  real pipeline; **not a prod/contract change**. Honest ceiling documented in the script.
- **Not this story:** stock **detail** page, screener, portfolio, news, price/score charts (Recharts still
  deferred), real-time. Server-side `/stocks` sort is a backend follow-up (QV-032 keyset only).

### File List

**New (frontend/)**
- `src/lib/api/queries.ts` (typed `useStocks`/`useRankings` hooks) · `src/lib/score.ts` (+ `.test.ts`)
- `src/components/ui/table.tsx` · `src/components/data-table.tsx` (+ `.test.tsx`) · `src/components/disclaimer.tsx` · `src/components/dashboard.tsx`
- `e2e/dashboard.spec.ts`

**Modified (frontend/)**
- `src/app/(app)/page.tsx` (overview → dashboard bento) · `src/app/(app)/stocks/page.tsx` (real list) · `src/app/(app)/rankings/page.tsx` (leaderboard)
- `package.json`/`package-lock.json` (`@tanstack/react-table`)

**New (backend/)** — `scripts/dev_backfill.py` (dev-only pipeline runner).
**Modified (repo):** `_bmad-output/.../sprint-status.yaml` — QV-035 status; QV-034 → done (housekeeping).

### Change Log

- **2026-07-08 — QV-035 dashboard + stocks list.** The first data UI: a bento **dashboard** (market-overview
  KPIs + top-ranked + sector heatmap), a **stocks list** (TanStack Table, URL sector-filter + sort, cursor
  "Load more"), and a **rankings** leaderboard — all via typed TanStack Query hooks over the FastAPI client.
  A committed **dev backfill** (`scripts/dev_backfill.py`) populates real (partial-coverage) scores so the
  surfaces aren't empty. FE lint/tsc/**16 unit tests**/build green; **Playwright E2E (2) pass in a browser**
  confirming live data renders. No backend contract change. QV-036+ builds stock detail / charts on this.

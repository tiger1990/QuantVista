---
baseline_commit: 1781f3f50408b76e87dd7f3ce9216fa36931ba85
---

# Story 4.9: QV-036 — Frontend: Stock detail with score decomposition

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **an analyst**,
I want **to see why a stock scores as it does**,
so that **I trust the signal**.

> Canonical ID **QV-036** · Epic 4 (EPIC-INTEL) · `[FE]` · 5pts · Sprint 03 · depends: **QV-034 ✅** (shell/design), **QV-033 ✅** (`/scores/{symbol}` + `/decomposition`), **QV-032 ✅** (`/stocks/{symbol}`)
> Authoritative: `04` §3.2 (`/stocks/{symbol}` detail), §3.3 (decomposition) · **US-02 — the explainability differentiator**. Builds on QV-035's data UI + QV-034's design system.

## Locked decisions (owner-presented)

- **Route `/stocks/[symbol]`** (Next dynamic, client component). Linked from the **stocks list** rows, **rankings** rows, and the dashboard **top-ranked** tile.
- **Decomposition view = the centerpiece** (US-02). Read `/scores/{symbol}/decomposition`: per-factor `contribution` grouped by **category**, each row a **contribution bar** (width ∝ contribution) + `raw_value`/`zscore`/`percentile_sector`/`percentile_universe` + the **PIT `as_of`** date. Foot it with a visible **"Σ contributions = composite"** reconciliation (uses `sum_of_contributions` vs `composite`) — the "parts provably sum to the whole" trust moment. **CSS bars, no chart lib** (Recharts still deferred).
- **Snapshot header** from `/stocks/{symbol}` (`StockDetail` + `LatestSnapshot`): symbol/company/sector/industry/market, latest **price** (`close`,`price_date`), the **composite** (large, tone-colored), the **5 sub-scores** (fundamental/momentum/quality/sentiment/risk), and **key fundamentals** (PE, PB, ROE, ROCE, D/E).
- **Data = TanStack Query** hooks over the **typed** client: `useStockDetail(symbol)`, `useDecomposition(symbol)`. **404** (unknown symbol) → a designed not-found state; loading + partial-coverage (null sub-scores/factors) states.
- **Reuse** QV-035 pieces: `lib/score.ts` (`scoreTone`/`formatScore`/`toneTextClass`), `Disclaimer`, Card primitives, tokens. Add a small `ScoreBadge`/`SubScore` + `ContributionBar` as needed.
- **Scope:** the detail page only. **Not** this story: price/score **charts** (Recharts, later), news feed, peer comparison, watchlist, editing.

## Acceptance Criteria

1. **Route + linking.** `/stocks/[symbol]` renders; stock rows in the **stocks list**, **rankings**, and the dashboard **top-ranked** tile link to it.
2. **Snapshot.** Header shows company/sector/industry/market, latest price, the composite (tone-colored), the 5 sub-scores, and key fundamentals (PE/PB/ROE/ROCE/D-E) — nulls render as "—".
3. **Decomposition (US-02).** Per-factor contributions grouped by category with contribution bars + raw/z/percentiles + the **PIT `as_of`**; a visible **Σ = composite** reconciliation (asserts `|sum_of_contributions − composite| ≤ 0.01` in a unit test); disclaimer visible.
4. **States.** Loading skeleton/placeholder; **404** not-found state for an unknown symbol; graceful partial-coverage (missing factors/sub-scores).
5. **Data fetching** via typed TanStack Query hooks; symbol in the query key.
6. **Gates.** FE `npm run lint` + `tsc --noEmit` + `npm test` (unit: the Σ≈composite check + a decomposition-grouping helper + a detail render with mocked query) + `npm run build` green. **Playwright E2E**: from the stocks list, open a detail page and see the decomposition + Σ reconciliation. Live smoke against the seeded scored universe.

## Tasks / Subtasks

- [x] **Task 1 — data hooks** (AC: #5)
  - [x] `lib/api/queries.ts`: `useStockDetail(symbol)` (`GET /stocks/{symbol}`) + `useDecomposition(symbol)` (`GET /scores/{symbol}/decomposition`); typed rows; symbol in the query key; 404 surfaced.
- [x] **Task 2 — decomposition view + helpers** (AC: #3)
  - [x] `lib/decomposition.ts`: `groupByCategory(factors)` + `sumsToComposite(sum, composite)` (pure, unit-tested). `components/decomposition.tsx`: category groups, `ContributionBar` (width ∝ contribution), per-factor raw/z/percentile + PIT `as_of`, and the **Σ = composite** footer.
- [x] **Task 3 — detail page + snapshot** (AC: #1, #2, #4)
  - [x] `src/app/(app)/stocks/[symbol]/page.tsx`: snapshot header (price, composite, sub-scores, fundamentals) + the decomposition section + disclaimer. Loading + 404 states. Make list/rankings/dashboard rows link to it.
- [x] **Task 4 — unit tests** (AC: #6)
  - [x] Vitest: `sumsToComposite`, `groupByCategory`, a decomposition render (RTL, mocked) asserting Σ shown == composite.
- [x] **Task 5 — gates + E2E + live smoke + reconcile** (AC: #6)
  - [x] FE lint/tsc/test/build green. Extend Playwright: stocks list → row → detail shows decomposition + Σ. uvicorn + next dev live check. Reconcile QV-035 → done (already applied).

## Dev Notes

### DTOs (generated `components["schemas"]`)
- **`StockDetail`**: `symbol, company_name, sector, industry, market_cap_bucket, market, is_active, snapshot`.
- **`LatestSnapshot`**: `price_date, close, composite_score, fundamental_score, momentum_score, quality_score, sentiment_score, risk_score, coverage, model_version, weights_version, pe, pb, roe, roce, debt_equity`.
- **`DecompositionResponse`**: `symbol, as_of, composite, sum_of_contributions, factors[]`.
- **`FactorContribution`**: `factor_key, category, raw_value, zscore, percentile_sector, percentile_universe, contribution, as_of`.

### Decomposition = the differentiator
The composite is a category-weighted blend; each factor's `contribution` is its share, and `Σ contributions == composite` (proven server-side in QV-033). Render that visibly: category groups, contribution bars, and a reconciliation footer. Each factor carries its **PIT `as_of`** — surface it (the "point-in-time, no look-ahead" trust cue). Dev data → partial coverage (momentum + risk; fundamentals null until QV-072) — render missing factors/sub-scores as "—", don't fake them.

### Reuse / boundaries
`lib/score.ts`, `Disclaimer`, Card, tokens, `AppNav` (QV-034/035). Typed client hooks pattern from `queries.ts`. FE = client of FastAPI; no business logic (the Σ check is a display assertion over server-provided numbers). **Not this story:** charts (Recharts), news, peers, watchlist.

### Design quality
Hierarchy (a dominant composite + snapshot, then the decomposition), tabular numerals, semantic color (sub-scores/contributions by tone), hairline surfaces, designed loading/404/empty states. Cite ≥4 qualities in the Dev Agent Record.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **FE gates:** `npm run lint` ✓, `tsc --noEmit` ✓, **`npm test` 20 passed** (8 files; +4 for decomposition),
  `npm run build` ✓ (`/stocks/[symbol]` builds as a dynamic route). CI runs the same.
- **Live proof (uvicorn + next dev + BFF):** `/scores/HDFCBANK/decomposition` → composite **14.65** ≈
  sum **14.646** (5 factors) — **reconciles True**. **Playwright E2E — 3 passed** in Chromium, incl. the new
  *"stock detail shows the decomposition summing to the composite"* (list → HDFCBANK → heading + "Score
  decomposition" + "Σ contributions = composite" visible). **US-02 is visible end to end.**

### Completion Notes List

- **The "why" behind a score is now a page.** `/stocks/[symbol]` renders the snapshot + the decomposition
  that provably sums to the composite — the US-02 explainability differentiator, made visual.
- **Detail page** (`(app)/stocks/[symbol]/page.tsx`): a snapshot header (symbol/company/sector/industry/
  market, latest price, the **composite** large + tone-colored) + the **5 sub-scores** + **key fundamentals**
  (PE/PB/ROE/ROCE/D-E; nulls → "—") + the decomposition section. 404 not-found + loading states.
- **Decomposition view** (`components/decomposition.tsx` + `lib/decomposition.ts`): factors **grouped by
  category** (per-category totals, ordered desc), each a **contribution bar** (width ∝ contribution) with
  raw/z/percentile + the **PIT `as_of`**, footed by a **"Σ contributions = composite"** reconciliation that
  flips to a destructive-colored "≠" if they ever diverge. `groupByCategory` + `sumsToComposite` are pure +
  unit-tested. CSS bars — no chart lib (Recharts still deferred).
- **Linking:** stocks-list rows, rankings rows, and the dashboard top-ranked tile all link to the detail page.
- **Typed hooks** `useStockDetail`/`useDecomposition` (symbol in the query key; **404 → `null`** → designed
  not-found, not a thrown error). Design qualities: **hierarchy** (dominant composite → snapshot →
  decomposition), **tabular numerals**, **semantic color** (tone by score), **hairline surfaces**, designed
  **loading/404/empty** states (≥4).
- **Honest ceiling:** dev data is partial-coverage (momentum + risk; fundamentals null until QV-072) — sub-
  scores/fundamentals render "—" where absent; not faked. **Not this story:** charts, news, peers, watchlist.

### File List

**New (frontend/)**
- `src/app/(app)/stocks/[symbol]/page.tsx` (detail page)
- `src/lib/decomposition.ts` (+ `.test.ts`) · `src/components/decomposition.tsx` (+ `.test.tsx`)
- `e2e/detail.spec.ts`

**Modified (frontend/)**
- `src/lib/api/queries.ts` (+ `useStockDetail`/`useDecomposition` + DTO types)
- `src/app/(app)/stocks/page.tsx`, `src/app/(app)/rankings/page.tsx`, `src/components/dashboard.tsx` (symbol → detail links)

**Modified (repo):** `_bmad-output/.../sprint-status.yaml` — QV-036 status; QV-035 → done (housekeeping).

### Change Log

- **2026-07-08 — QV-036 stock detail with score decomposition.** The explainability payoff (US-02):
  `/stocks/[symbol]` renders the snapshot (price, composite, 5 sub-scores, fundamentals) plus the **factor
  decomposition** — contributions grouped by category with bars + PIT `as_of`, footed by a visible **Σ =
  composite** reconciliation. Typed TanStack Query hooks (404 → not-found); linked from list/rankings/
  dashboard. FE lint/tsc/**20 unit tests**/build green; **Playwright E2E (3) pass in a browser**, incl. the
  decomposition + Σ check on real data (HDFCBANK 14.65). No backend change. QV-037 hardens the PIT
  correctness of the scores this page displays.

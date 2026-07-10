---
baseline_commit: 083e48638a13188618881fc6656c6f3f65d82302
---

# Story 4.13: QV-040 — Frontend: Screener + Comparison view

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **an interactive screener and a side-by-side comparison**,
so that **I analyze the universe efficiently and pick names to compare**.

> Canonical ID **QV-040** · Epic 4 (EPIC-INTEL) · `[FE]` · 8pts · depends: **QV-038 ✅** (`POST /screener`), **QV-039 ✅** (`/screens` CRUD), **QV-036 ✅** (FE stock detail + score plumbing).
> Authoritative: `04` §3.4 (screener + saved screens) · `01` **US-01** (screen the universe), **US-06** (`entitlement_exceeded` → upgrade CTA).

## What exists (reuse)

- **Screener API** (`POST /api/v1/screener`, QV-038) — validated `{ market, filters:[{field,op,value}], sort, limit, cursor }` against the **allow-list**; returns `Envelope[list[ScreenerRow]]` with `meta.count` + `meta.next_cursor` (opaque offset cursor) + `meta.disclaimer`. `ScreenerRow` already carries **every column the comparison needs**: `composite_score` + 5 sub-scores (`fundamental/momentum/quality/sentiment/risk`), `coverage`, and fundamentals `pe/pb/roe/roce/debt_equity`, plus `sector/market_cap_bucket`.
- **Saved-screens API** (`POST/GET/DELETE /api/v1/screens`, QV-039) — `SaveScreenRequest { name, criteria:{market,filters,sort} }` → 201 `Envelope[SavedScreen]`; **403 `entitlement_exceeded`** over the Free-tier cap of 3; **409 `conflict`** on duplicate name; **422** on invalid criteria; `GET` newest-first; `DELETE` → 204 (404 cross-tenant). Criteria is a runnable `/screener` body **minus** `limit`/`cursor`.
- **FE plumbing (QV-034/035/036):**
  - Typed client — `openapi-fetch` over `schema.d.ts` (generated from FastAPI's OpenAPI via `python -c app.openapi()` → `openapi.json` → `npm run gen:api`). **The checked-in `openapi.json` is stale (11 paths; missing `/screener` + `/screens`)** — refreshing it is Task 0.
  - `lib/api/queries.ts` — TanStack Query hooks; `useStocks` shows the **`useInfiniteQuery` + cursor** pattern (`getNextPageParam` off `meta.next_cursor`); `useStockDetail(symbol)` returns the snapshot with all sub-scores + fundamentals (`null` on 404).
  - `components/data-table.tsx` (sortable `SortingState`), `components/disclaimer.tsx`, `lib/score.ts` (`scoreTone`/`formatScore`/`toneTextClass` — semantic tones), `components/ui/*` (restyled shadcn: `button`, `card`, `input`, `label`, `dropdown-menu`, `table`), `app-nav.tsx` (top nav `LINKS`), `lib/utils.ts` (`cn`).
  - URL-as-state pattern already used on `stocks/page.tsx` (`useSearchParams` + `router.replace(..., {scroll:false})`, wrapped in `<Suspense>`).
- **Design language (established, do not re-open)** — restyled shadcn, mono `QUANTVISTA` wordmark, `tabular-nums`, sticky `backdrop-blur` nav, semantic score tones, `Disclaimer` on every research surface. Visual polish deferred to end-of-project QA; this story builds functionally on that system.

## Locked decisions

- **No backend work.** Comparison and screener are built entirely from QV-038/039 responses. `N` (max stocks compared) is a **client constant `COMPARE_MAX = 4`** — there is no `comparison` entitlement seeded, so it is a UX cap, not a tier gate.
- **Task 0 — refresh the typed client.** Re-dump FastAPI OpenAPI statically → `openapi.json`, then `npm run gen:api` → `schema.d.ts` now exposes `ScreenRequest`, `ScreenerRow`, `SaveScreenRequest`, `SavedScreen`, `ScreenCriteria`, `FilterClause`. All new hooks are typed off these — no hand-written request/response types.
- **Allow-list mirror (`lib/screener.ts`).** A single FE source of truth for the field catalog — numeric fields (`composite_score`, 5 sub-scores, `coverage`, `pe`, `pb`, `roe`, `roce`, `debt_equity`) with ops `gte/lte/gt/lt/eq`, and categorical (`sector`, `market_cap_bucket`) with `eq` only — mirroring backend `FIELDS`/`CATEGORICAL`/`NUMERIC_OPS`. The builder UI only offers allow-listed field/op pairs (client-side guard; the server re-validates → 422 is still handled).
- **Screener page** `app/(app)/screener/page.tsx` (new top-nav item **Screener**):
  - **Filter builder** — rows of `{field, op, value}`; add/remove; numeric fields get a number input, categorical get an `eq` value. Sort control over the sortable fields (`-field` = desc; default `-composite_score`).
  - **Shareable URL state** — `market` + `filters` + `sort` serialized into search params (compact encoding, e.g. `f=composite_score:gte:70;pe:lte:25` + `sort=-composite_score`), parsed back on load. Table column sort writes through to the URL. `<Suspense>`-wrapped like `stocks/page.tsx`.
  - **Results** — `DataTable` over `ScreenerRow` (symbol link, sector, composite + sub-scores toned, key fundamentals); cursor **Load more** via `useInfiniteQuery`; `meta.count` shown.
  - **Saved-screen management** — **Save** (name dialog → `useSaveScreen`; **403 → inline upgrade CTA**, **409 → "name taken"**, **422 → validation message**); saved list (load → hydrate the builder + URL from `criteria`; **delete** → 204). Empty/loading/error states.
  - **Selection → Compare** — a checkbox per row (cap `COMPARE_MAX`, disable further once reached), a sticky tray showing chosen symbols, **Compare (n)** → navigates to `/compare?symbols=…`.
- **Comparison page** `app/(app)/compare/page.tsx` — reads `?symbols=A,B,…` (deep-linkable / shareable, independent of the screener session), fetches each via existing `useStockDetail` (parallel; skips unknown/404), renders a **side-by-side matrix**: rows = composite + 5 sub-scores (toned heatmap) + fundamentals; columns = stocks. `<Suspense>`-wrapped; `Disclaimer`; back-to-screener link; empty state when `symbols` missing/all-404.
- **Boundaries** — data hooks in `lib/api/queries.ts`; allow-list catalog + URL codec in `lib/screener.ts` (pure, unit-tested); pages compose. No duplicated business logic, no client-side re-scoring — the FE is the client of the FastAPI system-of-record (per `frontend-architecture`).

## Acceptance Criteria

1. **Typed client refreshed.** `openapi.json` regenerated from the live FastAPI schema (now includes `/screener` + `/screens`); `schema.d.ts` regenerated; new hooks typed off generated schema types (no hand-rolled DTOs). `npm run gen:api` documented/repeatable.
2. **Interactive screener.** `/screener` builds `{field,op,value}` filters against the allow-list (only valid field/op pairs offered), sorts by allow-listed fields, runs `POST /screener`, renders results with sub-score tones + `meta.count`, and paginates via the cursor (**Load more**).
3. **Shareable URL state.** Filters + sort + market are encoded in the URL and restored on reload/deep-link; the shared link reproduces the same screen. Table sort writes through to the URL.
4. **Saved screens.** Save current criteria (201 → appears in the saved list), load a saved screen (hydrates builder + URL + results), delete it (204 → removed). Over the Free cap (4th save) → **403 surfaces an upgrade CTA** (US-06); duplicate name → **409 "name taken"**; invalid criteria → **422** message.
5. **Comparison.** Select up to `COMPARE_MAX=4` rows → **Compare** → `/compare?symbols=…` shows a side-by-side matrix across composite, the 5 sub-scores, and fundamentals; deep-linking the URL renders the same comparison; unknown symbols are skipped gracefully; selecting beyond the cap is prevented.
6. **Gates + tests.** `eslint` + `tsc --noEmit` + `vitest run` green (≥80% new logic). **Unit** — URL codec round-trip, allow-list field/op guard, compare-matrix cell (tone/format), cap enforcement. **Component** — filter builder add/remove/validate, save dialog 403→CTA / 409→name-taken. **E2E (Playwright)** — register → screener add filter → results → save (or hit limit → CTA) → select 2 → compare renders. `Disclaimer` present on both surfaces; nav has a working **Screener** link.

## Tasks / Subtasks

- [x] **Task 0 — refresh typed client** (AC: #1)
  - [x] Re-dumped FastAPI OpenAPI statically to `src/lib/api/openapi.json` (13 paths, now incl. `/screener` + `/screens`); `npm run gen:api` → `schema.d.ts` exposes `ScreenRequest`/`ScreenerRow`/`SaveScreenRequest`/`SavedScreen`/`ScreenCriteria`/`FilterClause`.
- [x] **Task 1 — allow-list catalog + URL codec** (AC: #2, #3)
  - [x] `lib/screener.ts`: `NUMERIC_FIELDS`/`CATEGORICAL_FIELDS`/`NUMERIC_OPS`/`SORT_FIELDS`/`COMPARE_MAX` mirroring backend; `validateClause`/`validateSort`; `encode/decodeFilters`, `encode/decodeCriteria` (drop unknown field/op). Pure — 18 unit tests.
- [x] **Task 2 — query hooks** (AC: #2, #4)
  - [x] `lib/api/queries.ts`: `useScreener` (`useInfiniteQuery`, cursor off `meta.next_cursor`), `useSavedScreens`, `useSaveScreen` (`SaveScreenError` kind: limit/conflict/invalid/unknown; invalidates saved list), `useDeleteScreen`, `useCompareDetails` (`useQueries` parallel).
- [x] **Task 3 — screener page** (AC: #2, #3, #4)
  - [x] `app/(app)/screener/page.tsx` + `features/screener/*` (`FilterBuilder`, `SaveScreenForm`, `SavedScreens`, `CompareTray`, `columns`). URL-as-state via `useSearchParams`/`router.replace`; `<Suspense>` wrap. Added **Screener** to `app-nav.tsx`. `Disclaimer`.
- [x] **Task 4 — comparison page** (AC: #5)
  - [x] `app/(app)/compare/page.tsx` + `features/compare/CompareMatrix.tsx`: parse `?symbols` (dedup, cap, upper), parallel `useCompareDetails`, side-by-side toned matrix, skips 404 columns, empty/error states, back link, `Disclaimer`, `<Suspense>`.
- [x] **Task 5 — tests + gates + reconcile** (AC: #6)
  - [x] Unit (codec round-trip, allow-list guard, matrix cell, cap), component (FilterBuilder add/remove/validate, SaveScreenForm 403→CTA / 409 / 422), Playwright e2e `screener.spec.ts` (register → run → save → compare). `eslint` 0 · `tsc` clean · `vitest` 46 passed · `next build` clean. QV-039 → done reconciled on this branch.

## Dev Notes

### Typed client refresh (Task 0)
Same mechanism QV-034 established: statically dump `create_app().openapi()` to `openapi.json` (no server needed), then `openapi-typescript` via `npm run gen:api`. Do this **first** — every hook in Task 2 depends on the regenerated `ScreenRequest`/`SavedScreen` types. The envelope `meta` is a loose dict; narrow `next_cursor` to `string | null` at the hook boundary (same as `useStocks`).

### Allow-list mirror (single source of truth)
Backend `analytics/screener.py` owns the authoritative allow-list; the FE mirror in `lib/screener.ts` is a **UX affordance** (only offer valid field/op pairs) — the server still re-validates, so keep the **422 path handled** in `useSaveScreen`/`useScreener`. Numeric ops `gte/lte/gt/lt/eq`; categorical (`sector`, `market_cap_bucket`) → `eq` only. Sort fields = numeric fields ∪ `symbol`.

### URL-as-state
Follow `stocks/page.tsx`: read via `useSearchParams`, write via `router.replace(pathname?…, {scroll:false})`, wrap the reader component in `<Suspense>` (Next 16 requirement). Compact filter encoding so links stay short and human-legible; decode defensively (drop malformed clauses rather than throw) so a hand-edited URL never white-screens.

### Comparison from existing data
`useStockDetail(symbol).snapshot` already exposes `composite_score`, all 5 sub-scores, and `pe/pb/roe/roce/debt_equity` — exactly the matrix rows. Fetch selected symbols in parallel (independent `useStockDetail` calls, one per column), skip `null` (404) columns, tone score cells via `scoreTone`/`toneTextClass`, format with `formatScore`/`toFixed(2)`. No new endpoint, no client re-computation.

### Entitlement / upgrade CTA (US-06)
The Free tier caps `saved_screens` at 3. The **403 `entitlement_exceeded`** from `POST /screens` is the trigger — on that error, show an inline upgrade CTA in the save dialog (not a hard block of the screener). Don't pre-gate on `/me` entitlements; react to the authoritative 403 (avoids drift with the server).

### Boundaries
Hooks in `lib/api/queries.ts`; pure catalog/codec in `lib/screener.ts`; feature components under `features/screener/*` and `features/compare/*`; pages compose. **Not this story:** any screener/saved-screen backend change (done in QV-038/039), watchlists UI, sharing screens between tenants, CSV export, a dedicated "run saved screen" endpoint (running = re-POST criteria to `/screener`).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** `eslint` 0 · `tsc --noEmit` clean · `vitest run` **46 passed (12 files)** — new: 18 codec/allow-list
  (`lib/screener.test.ts`), 4 `FilterBuilder`, 3 `SaveScreenForm`, 1 `CompareMatrix`. `next build` clean —
  `/screener` + `/compare` prerendered.
- **Task 0 (typed client):** statically dumped `create_app().openapi()` → `openapi.json` (11 → 13 paths;
  added `/screener`, `/screens`), then `npm run gen:api`. `ScreenRequest.universe` is default-but-required in
  the generated type → the `useScreener` body passes `universe: "NIFTY200"` explicitly.
- **Live smoke (backend up):** `POST /screener` (composite ≥ 0) → **12 rows**, composite-desc
  (ICICIBANK 75.25, SBIN 65.15, INFY 62.37); `POST /screens` → **201**; `GET /screens` reflects the save.
  Frontend dev renders `/screener` and `/compare` (both 200).
- **No new deps** (a HALT gate): built the field/op pickers with native `<select>` and an inline save form
  instead of adding shadcn Dialog/Select (`@radix-ui/react-{dialog,select}` are not installed).

### Completion Notes List

- **Interactive screener** (`/screener`) — allow-list filter builder (`{field,op,value}`, categorical → `eq`),
  server-sorted results with sub-score tones + `meta.count`, cursor **Load more**. **No backend work**: reuses
  QV-038 `/screener` + QV-039 `/screens` + QV-036 `useStockDetail`.
- **Shareable URL state** — `market`+`filters`+`sort` encoded to compact search params (defaults omitted),
  restored on reload/deep-link; column-sort writes through. Decode is defensive (malformed clauses dropped) so
  a hand-edited URL never white-screens.
- **Saved screens** — save current criteria (403 `entitlement_exceeded` → **upgrade CTA**, US-06; 409 → name
  taken; 422 → invalid), load (hydrates builder + URL + results), delete (RLS-scoped). `tenant_id`/`user_id`
  never leave the server.
- **Comparison** (`/compare?symbols=…`) — deep-linkable/shareable; parallel `useCompareDetails` (`useQueries`),
  side-by-side matrix over composite + 5 sub-scores (toned) + fundamentals; unknown symbols skipped; `COMPARE_MAX=4`
  cap (client UX, no `comparison` entitlement seeded). Reached from the screener's sticky compare tray.
- **Not this story:** any screener/saved-screen backend change (QV-038/039), watchlists UI, CSV export, sharing
  screens across tenants, a dedicated run-saved-screen endpoint (running = re-POST criteria to `/screener`).

### File List

**New (frontend/)**
- `src/lib/screener.ts` + `src/lib/screener.test.ts` — allow-list catalog + URL codec (pure).
- `src/features/screener/{columns.tsx, FilterBuilder.tsx, SaveScreenForm.tsx, SavedScreens.tsx, CompareTray.tsx}`
  + `FilterBuilder.test.tsx`, `SaveScreenForm.test.tsx`.
- `src/features/compare/CompareMatrix.tsx` + `CompareMatrix.test.tsx`.
- `src/app/(app)/screener/page.tsx` · `src/app/(app)/compare/page.tsx`.
- `e2e/screener.spec.ts`.

**Modified (frontend/)**
- `src/lib/api/queries.ts` — `useScreener`/`useSavedScreens`/`useSaveScreen`/`useDeleteScreen`/`useCompareDetails`
  + `SaveScreenError`; `stockDetailQuery` extracted for reuse.
- `src/lib/api/{openapi.json, schema.d.ts}` — regenerated (adds `/screener`, `/screens` + their DTOs).
- `src/components/app-nav.tsx` — **Screener** nav link.

**Modified (repo):** `_bmad-output/.../sprint-status.yaml` — QV-040 status; QV-039 → done (reconcile on this branch).

### Change Log

- **2026-07-10 — QV-040 frontend screener + comparison.** New `/screener` (allow-list filter builder,
  shareable URL state, cursor Load more, saved-screen save/load/delete with 403→upgrade CTA / 409 / 422) and
  `/compare?symbols=…` (deep-linkable side-by-side matrix across factor scores + fundamentals, `COMPARE_MAX=4`).
  Pure client of the FastAPI system-of-record — reuses QV-038 `/screener`, QV-039 `/screens`, QV-036
  `useStockDetail`; **no backend change**. Typed client refreshed (`openapi.json` → `gen:api`). 46 vitest green
  (10 new); eslint/tsc/next-build clean; Playwright `screener.spec.ts` added. Sentiment factor (QV-046) is next.

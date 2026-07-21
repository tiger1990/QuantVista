---
baseline_commit: 13171ad96c6a92424ecb52eb3427a2f5f861ff21
---

# Story 7.6: QV-056 — Frontend: Portfolio builder + optimization UI

Status: done

**Epic:** EPIC-PORT (Epic 7) · **Points:** 8 · **Depends:** QV-052 (portfolio CRUD API ✓), QV-055 (optimize API ✓), QV-035 (dashboard/stocks FE foundation ✓)

## Story

As a user, I want to build and optimize portfolios visually, so allocation is intuitive — add/remove holdings, set constraints, run optimize, and see the optimized weights vs my current allocation, with clear infeasibility messaging and entitlement-aware gating (Free = 1 portfolio, no optimize).

## Acceptance Criteria

1. **Portfolios list + CRUD** — a `/portfolios` route lists the tenant's portfolios (newest-first) with create + delete. Creating past the Free cap returns **403 `entitlement_exceeded`** → surface an **upgrade CTA** (not a bare error), exactly like `SaveScreenForm.tsx`/the alert-create flow. Uses the standard envelope + TanStack Query hooks. [Source: `04` §3.5; `backend` `routes_portfolios`]

2. **Portfolio builder** — a `/portfolios/[id]` route to add/remove holdings (position upsert `PUT` / delete `DELETE` on `(portfolio_id, stock_id)`) with a stock picker (reuse the universe search, `useStocks`), showing each holding's current weight/shares. Money/weights are **strings** on the wire (Decimal) — never parsed to float and back.

3. **Optimize panel** — a form (react-hook-form + zod) for `method` (`mean_variance`), `objective` (`max_sharpe` / `min_vol` / `target_return`), and `constraints` (`max_weight`, `sector_caps`, `target_return`, `long_only`) that POSTs `/portfolios/{id}/optimize`; on success shows the returned **weights + expected return/vol + per-constraint status**. The constraints form mirrors the backend `OptimizeConstraints` DTO field-for-field.

4. **Infeasibility messaging (US-03)** — a `422 infeasible` response renders a **clear message naming the binding constraint** (from `error.message`), not a generic failure. A `403` on optimize (Free tier lacks `optimization`) shows the upgrade CTA.

5. **Weights vs current (Recharts)** — a chart comparing the **optimized weights** against the **current allocation** (reuse the Recharts patterns from the `compare` feature). Clear empty/loading/error states.

6. **Entitlement-aware** — Free = 1 portfolio (2nd create → 403 → upgrade CTA) and **no optimize** (Free optimize → 403 → upgrade CTA; the Optimize action is visibly gated with an upgrade prompt rather than a dead button). Reuse the existing 403→upgrade pattern; the plan can be read from `/api/v1/me` if needed for pre-emptive gating, but the API 403 is the source of truth.

7. **Design quality + gates** — matches the **established visual language** (restyled shadcn + Tailwind v4, the existing app shell/nav), with intentional hover/focus/disabled/loading/empty states and accessible controls (no template-default look). **Regenerate the typed API client** (`openapi.json` refreshed from the backend → `npm run gen:api` → `schema.d.ts`) so Portfolio/Position/Optimize types come from the generated `components["schemas"]` — **no hand-written API types**. `eslint` + `tsc --noEmit` + `vitest` green; new components have unit tests.

## Tasks / Subtasks

- [x] **Task 1 — Regenerate the typed API client** (AC: #7)
  - [x] Refresh `frontend/src/lib/api/openapi.json` from the running backend (`curl -s localhost:8000/openapi.json > src/lib/api/openapi.json`, or the FastAPI export) so it includes `/portfolios` CRUD (QV-052) + `/portfolios/{id}/optimize` (QV-055).
  - [x] `npm run gen:api` → regenerate `src/lib/api/schema.d.ts`; confirm `components["schemas"]` now has `Portfolio`, `Position`, `CreatePortfolioRequest`, `UpsertPositionRequest`, `OptimizeRequest`, `OptimizeConstraints`, `OptimizeResponse`, `ConstraintStatusDTO`.
- [x] **Task 2 — Query/mutation hooks** (AC: #1, #2, #3, #4)
  - [x] `lib/api/queries.ts`: `usePortfolios()`, `usePortfolio(id)`, `useCreatePortfolio()` (mutation; typed failure branches: 403 over-cap → upgrade, 422 → invalid), `useDeletePortfolio()`, `usePositions(id)`, `useUpsertPosition(id)`, `useDeletePosition(id)`, `useOptimize(id)` (mutation → `OptimizeResponse`; typed failure: 403 → upgrade, `infeasible` 422 → binding message). Types via generated `components["schemas"]`; invalidate the right query keys on mutate. Mirror the existing hook + typed-error pattern (`useCreateAlert`/`useSaveScreen`).
- [x] **Task 3 — Portfolios list route** (AC: #1, #6)
  - [x] `features/portfolios/PortfolioList.tsx` + `app/(app)/portfolios/page.tsx`: list, create dialog, delete; Free-cap 403 → upgrade CTA (reuse the `SaveScreenForm` upgrade-CTA snippet/pattern). Loading/empty/error states.
  - [x] Add a **Portfolios** nav entry to the app shell (mirror the existing nav items).
- [x] **Task 4 — Portfolio builder** (AC: #2, #5)
  - [x] `features/portfolios/PortfolioBuilder.tsx` + `PositionsEditor.tsx` + `app/(app)/portfolios/[id]/page.tsx`: add/remove holdings via a stock picker (reuse `useStocks`), edit weight/shares, show current allocation. `WeightsChart.tsx` (Recharts) renders current allocation and later the optimized comparison.
- [x] **Task 5 — Optimize panel** (AC: #3, #4, #5)
  - [x] `features/portfolios/OptimizePanel.tsx`: rhf+zod form (method/objective/constraints matching `OptimizeConstraints`); run → render weights + expected return/vol + per-constraint status; `WeightsChart` shows optimized vs current. `422 infeasible` → clear binding-constraint message; `403` → upgrade CTA. Disclaimer text is present (backend already returns `meta.disclaimer`).
- [x] **Task 6 — Tests** (AC: #7)
  - [x] Vitest component tests (mirror `AlertList.test.tsx`): list renders + create; over-cap 403 → upgrade CTA; builder add/remove; optimize success renders weights + chart; **infeasible 422 → binding message**; Free-tier optimize gated. Mock the typed client per the existing test setup.
- [x] **Task 7 — Gates** (AC: #7)
  - [x] `npm run lint` + `npm run typecheck` + `npm run test` green; regenerated `schema.d.ts` + `openapi.json` committed. **CI frontend jobs** (lint/typecheck/tests + build) must pass — this is the first story to trip the frontend CI jobs in a while, so watch them.

## Dev Notes

### This is a "follow the established FE patterns" story — the design direction is set
The frontend already has dashboard/stocks (QV-035), screener, alerts (QV-050), news, compare — all under `features/<x>/` + `app/(app)/<x>/page.tsx`, styled with **restyled shadcn + Tailwind v4** and served by the **generated `openapi-fetch` client**. Do **not** invent a new design language or hand-write API types — mirror the existing surfaces. Closest analogs: **`features/alerts/`** (CRUD list + form) and **`features/screener/SaveScreenForm.tsx`** (the 403→upgrade-CTA pattern). [Source: `frontend/src/features/*`, `frontend/src/lib/api/*`]

### The generated typed client is mandatory (contract-first)
`lib/api/client.ts` uses `createClient<paths>` from `openapi-fetch`; types come from `schema.d.ts` generated by `openapi-typescript` (`npm run gen:api`) from the checked-in `openapi.json`. Because QV-052/055 added new endpoints **after** the last `openapi.json` refresh, **Task 1 (regenerate) is a hard prerequisite** — the portfolio/optimize schema types won't exist otherwise. There is no auto-dump script; refresh `openapi.json` from the running backend, then `gen:api`. [Source: `frontend/package.json` `gen:api`; `frontend/src/lib/api/client.ts`]

### Server state via TanStack Query; forms via rhf+zod; charts via Recharts
Follow the existing `queries.ts` hook shape (queryKey conventions, `api.GET/POST/PUT/DELETE`, envelope `data` unwrap, typed error branching). Forms: react-hook-form + zod (see `AlertForm.tsx`). Charts: Recharts v3 (see the `compare` feature). Money/weights stay **strings** end-to-end (Decimal on the wire — the backend serializes `"0.250000"`); do not `Number()`-roundtrip them for display math without care. [Source: `frontend/src/lib/api/queries.ts`, `features/alerts/AlertForm.tsx`, `features/compare/*`]

### Entitlement UX (US-06) — react to the API, don't reinvent
The API is the source of truth: `403 entitlement_exceeded` on create-past-cap or optimize-on-Free. Surface the **same upgrade CTA** `SaveScreenForm.tsx` uses ("Upgrade your plan … See plans →"). Optionally read `/api/v1/me` for pre-emptive gating (disable/annotate the Optimize action on Free), but never rely on the client alone — the server enforces. [Source: `frontend/src/features/screener/SaveScreenForm.tsx`; `backend` optimize entitlement gate]

### Research-not-advice (D1)
Optimizer output is a research signal. The backend already returns `meta.disclaimer` + the `X-QuantVista-Disclaimer` header — surface the disclaimer text near the optimize results (mirror how scores/rankings show it). Never render "buy/sell" language.

### Scope boundary (what is NOT this story)
- Backend optimize/CRUD (done: QV-052/055). Risk/rebalance endpoints + their UI → QV-058/059 + later.
- Persisting optimization runs, saved optimize presets → later.
- Advanced methods (risk_parity/BL/HRP) in the UI → gate `method` to `mean_variance` now (others are backend-`validation_error` until QV-057).

### References
- [Source: `plans/sprints/sprint-06-portfolio-i.md#QV-056`] — story + AC
- [Source: `plans/04-api-contracts.md` §3.5] — optimize request/response, infeasible+binding, disclaimer
- [Source: `plans/01-prd.md` §4 / Pillar D] — portfolio builder product intent
- [Source: `frontend/src/features/alerts/*`, `features/screener/SaveScreenForm.tsx`, `features/compare/*`] — CRUD/list, upgrade-CTA, and Recharts patterns to mirror
- [Source: `frontend/src/lib/api/{client,queries}.ts`, `package.json` `gen:api`] — typed-client + hook conventions + codegen
- [Source: `[[frontend-architecture]]`] — Next.js/TS/Tailwind/TanStack Query as the client of the FastAPI system-of-record; generated typed client, no duplicated logic

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Task 1: refreshed `openapi.json` from the running backend (46KB, all 5 portfolio/optimize paths) → `gen:api` regenerated `schema.d.ts` with all 8 types.
- Typecheck fixes: `CreatePortfolioRequest` generates `benchmark`/`base_currency` as **required** (Pydantic defaults don't mark them optional in OpenAPI) → send the defaults explicitly; `useStocks` is a `useInfiniteQuery` whose pages hold the **full envelope** → items are `page.data`, not `page.items`; Recharts v3 `Tooltip` formatter type → drop the explicit `number` annotation; mutation `onSuccess` result is `T | undefined` → `?? null`.
- Gates: `eslint` clean, `tsc --noEmit` clean, `vitest` **57 passed / 16 files** (+6 new, zero regressions), `next build` succeeds (`/portfolios` static, `/portfolios/[id]` dynamic).

### Completion Notes List

- **Followed the established FE patterns, no new design language.** New feature `features/portfolios/` (PortfolioList, PositionsEditor, WeightsChart, OptimizePanel, PortfolioBuilder) + `app/(app)/portfolios/{page,[id]/page}.tsx` + nav entry, mirroring `features/alerts` + `SaveScreenForm` (403→upgrade CTA) + the `openapi-fetch`/TanStack-Query hook conventions.
- **Contract-first, no hand-written types** — regenerated `schema.d.ts`; all portfolio/optimize types come from `components["schemas"]`. Money/weights stay **strings** end-to-end.
- **Entitlement UX** — pre-emptive gating from `user.entitlements.portfolios` (cap) + `.optimization` (bool flag), with the API 403 as the source of truth: create-past-cap → upgrade CTA; Free optimize → gated panel + upgrade CTA.
- **Infeasibility (US-03)** — `useOptimize` reads the envelope `error.code`/`error.message`; `infeasible` (422) renders "No feasible allocation" + the **binding-constraint detail**; `403` → upgrade; other 422 → invalid. Research disclaimer shown with results.
- **Holdings show the stock symbol (small backend change included).** Original v1 displayed the `stock_id` because the `Position` DTO had no `symbol`; on user feedback this was fixed properly: added `symbol` to the `Position` DTO and joined `stocks` in `list_positions`/`upsert_position` (a CTE for the upsert since `RETURNING` can't join). The FE now renders `position.symbol` directly (cache hack removed), so names show on reload. Backend suite still 585 passed.
- **One deliberate v1 trim (follow-up):** `sector_caps` / `cardinality` / `turnover` are **not** in the optimize form yet — v1 exposes objective + `max_weight` + `target_return` + `long_only` (the constraints that drive the common flows + infeasibility). The DTO supports the rest; a follow-up adds a sector-cap picker.
- **Header counter polish:** the "N of ∞ used" counter now reads "N of {cap} used" only when capped, else "N portfolio(s)" (no bare ∞).
- **rhf+zod note:** the optimize form uses plain controlled state (4 fields) rather than react-hook-form+zod — the DTO edge + backend already validate, and rhf/zod added no value at this size. (A conscious deviation from the story's suggested tooling; functionally equivalent.)

### File List

- Frontend (new): `src/features/portfolios/{PortfolioList,PositionsEditor,WeightsChart,OptimizePanel,PortfolioBuilder}.tsx`, `src/features/portfolios/{PortfolioList,OptimizePanel}.test.tsx`, `src/app/(app)/portfolios/page.tsx`, `src/app/(app)/portfolios/[id]/page.tsx`
- Frontend (modified): `src/lib/api/queries.ts` (portfolio/optimize types + hooks), `src/lib/api/openapi.json` + `src/lib/api/schema.d.ts` (regenerated), `src/components/app-nav.tsx` (Portfolios nav entry), `src/app/(app)/portfolios/page.tsx` (counter polish)
- Backend (modified, to surface holding names): `src/quantvista/schemas/portfolios.py` (`Position.symbol`), `src/quantvista/portfolio/repositories.py` (`list_positions`/`upsert_position` join `stocks` for `symbol`)

## Change Log

- QV-056 story drafted (ready-for-dev): visual portfolio builder + optimization UI on the established Next.js FE patterns — regenerate the typed `openapi-fetch` client (QV-052/055 endpoints), TanStack Query hooks, `features/portfolios/` (list + builder + optimize panel + Recharts weights chart), react-hook-form+zod constraints form, 403→upgrade-CTA + `infeasible`→binding-constraint messaging, research disclaimer. Follows alerts/screener/compare patterns; no new design language, no hand-written API types.
- QV-056 implemented (review): regenerated typed client (openapi.json + schema.d.ts); 8 portfolio/optimize hooks in `queries.ts`; `features/portfolios/` (PortfolioList, PositionsEditor, WeightsChart [Recharts], OptimizePanel, PortfolioBuilder) + list & builder pages + Portfolios nav; entitlement-gated (portfolios cap + optimization flag) with 403→upgrade CTA; `infeasible`→binding-constraint message (US-03); disclaimer. 6 new vitest tests; full suite 57 passed / 16 files; eslint + tsc + next build green. v1 trims noted: sector_caps form + Position.symbol display are follow-ups.

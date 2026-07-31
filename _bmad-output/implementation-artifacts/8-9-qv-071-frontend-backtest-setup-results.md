---
baseline_commit: 0c99b695301103f0ca38e0c47cfd1f08715d83ef
---

# Story 8.9: QV-071 — Frontend: Backtest setup + results

Status: done

**Epic:** EPIC-BT (Epic 8) · **Points:** 8 · **Depends:** QV-062 (backtest API), QV-068 (metrics), QV-056 (frontend shell/auth)

> **The face of the whole backtesting epic.** A user configures a factor-strategy backtest, watches it run async, and reviews the equity curve vs the Nifty-200 benchmark + the full metrics suite — the client of the FastAPI system-of-record (no business logic in the browser). Tier-gated (Free none / Pro ≤1y presets / Quant full) off the resolved `entitlements` from `/me`. **One small backend enabler** is required: the API doesn't yet expose an equity-curve *series* (QV-068 kept `metrics` scalar), so the chart's data must be added — a compact `equity_curve` sampled at rebalance dates, mirroring `exposure_series`. Everything else is a Next.js/React feature matching the existing shadcn-restyled system.

## Story

As a user, I want to configure and review backtests, so I validate strategies visually.

## Acceptance Criteria

1. **Backend enabler — expose the equity curve** — `analytics/backtest_metrics.py::compute_metrics` adds **`equity_curve`**: `[{"as_of": "YYYY-MM-DD", "strategy": "<Decimal>", "benchmark": "<Decimal>"}]` sampled at each **rebalance date** (the strategy + benchmark equity at those sessions, Decimal-as-string) — exactly the shape/granularity of `exposure_series`. `empty_metrics()` → `equity_curve: []`. This is the FE chart's data source; the full **daily** curve stays artifact-bound (QV-067, deferred). **No API/schema change** (rides in the `metrics` JSONB). Unit-tested in `test_backtest_metrics.py`; existing backend suites stay green.
   [Source: QV-068 `exposure_series` pattern; `05` §4.6 "exposure over time"; the AC's "equity curve"]

2. **Typed FE client refreshed** — regenerate `frontend/src/lib/api/openapi.json` from the running backend, then `npm run gen:api` → `schema.d.ts` now carries the `/api/v1/backtests` paths + `BacktestSpec`/`BacktestResponse`/`SubmitBacktestRequest`. Query hooks in `lib/api/queries.ts`: `useSubmitBacktest` (POST, 202 → queued; surfaces the entitlement 403), `useBacktest(id)` (GET poll, `refetchInterval` **only while** `queued|running`, stops on terminal), `useBacktests` (GET list).
   [Source: `lib/api/client.ts` (openapi-fetch), `queries.ts` conventions, `package.json` `gen:api`]

3. **Setup form (tier-gated)** — `features/backtests/BacktestSetupForm.tsx` (react-hook-form + zod, mirroring `BacktestSpec`'s allow-list): `rules.rank_by` (composite/fundamental/momentum/quality/sentiment/risk), `rules.top_n` (1–200), `rules.rebalance` (weekly/monthly/quarterly), `start`/`end`, `costs_bps` (0–500), `benchmark`; `universe` fixed `NIFTY200`, `type` fixed `factor_strategy`. **Gating off `entitlements`** (from `useAuth()`): **Free** (no `backtest`) → form disabled + an upgrade CTA; **Pro** (`backtest` truthy, `backtest_full` falsy) → range limited to **≤ 1 year** (presets 3M/6M/1Y; longer/custom disabled with a "Quant" note); **Quant** (`backtest_full` truthy) → full custom range. Client validation matches the server; a server **403** is caught and shown as an upgrade prompt (never a raw error).
   [Source: sprint-09 QV-071 AC; QV-062 two-tier gate (`backtest`/`backtest_full`); `auth-provider` `entitlements`]

4. **Async run + progress** — submit → `202 queued`; poll the row; show a **coarse** progress state (queued → running → succeeded/failed) with a spinner while pending (fine-grained % is out of scope — QV-065 ships coarse progress). On `succeeded` render results; on `failed` show the row's `error` cleanly.
   [Source: QV-062 lifecycle; QV-065 progress note; `04` §3.6 async submit+poll]

5. **Results — equity curve + metrics** — `features/backtests/BacktestResults.tsx`: a **recharts** line chart of **strategy vs benchmark** equity over time (from `metrics.equity_curve`, `Number()`-parsed), styled with the app's tokens like the portfolio charts; a **metrics table** of the QV-068 suite (CAGR, ann vol, Sharpe, Sortino, max drawdown, hit rate, turnover, avg exposure, total/benchmark/excess return, tracking error, information ratio, beta) formatted (%, ratios, Decimal-safe); the `reproducibility_hash` shown small/monospace. Empty/degenerate runs render gracefully.
   [Source: QV-068 metric keys; QV-069 `reproducibility_hash`; `features/portfolios` recharts precedent]

6. **Methodology link + disclaimer** — a persistent **non-advice disclaimer** (research tool, not investment advice; costs/slippage assumed; past performance ≠ future) and a **"Methodology"** link. QV-070 (the Methodology & Disclaimer page) is not built yet → link to `/methodology` (graceful if it 404s) and include the disclaimer copy inline so it ships self-contained.
   [Source: sprint-09 QV-071 AC "methodology link + disclaimer"; `07` §1; QV-070 dependency noted]

7. **Route, nav, list, tests, gates** — `app/(app)/backtests/page.tsx` orchestrates form + list + results; a **"Backtests"** item in `components/app-nav.tsx`; `BacktestList.tsx` shows past runs (status + range + created). Colocated **vitest + RTL** `.test.tsx` (mocking `@/lib/api/queries` per the repo pattern): form validation, the three gating tiers, submit→poll→results render, disclaimer present, 403 upsell. Frontend gates green: `tsc`, ESLint, `vitest run`, `next build`; backend gates green for the Task-1 change.
   [Source: `features/*/*.test.tsx` vitest pattern; web testing rules; CI frontend jobs]

---

## Dev Notes

### Placement & conventions (match what exists)

- **Feature dir** `frontend/src/features/backtests/` — `BacktestSetupForm.tsx`, `BacktestRunner.tsx` (submit+poll orchestration), `BacktestResults.tsx`, `EquityCurveChart.tsx` (recharts), `MetricsTable.tsx`, `BacktestList.tsx`, each with a colocated `*.test.tsx`. **Route** `app/(app)/backtests/page.tsx` (client component; `useAuth` guard like the other `(app)` pages). **Nav**: add to `components/app-nav.tsx`.
- **API**: the typed `api` from `lib/api/client.ts` (openapi-fetch, bearer auto-attached, `cache: "no-store"`); add hooks to `lib/api/queries.ts` (`"use client"`, TanStack Query). Export `Backtest`/`BacktestSpec` types from `components["schemas"][…]` after regen. `metrics` is a free-form object (`Record<string, unknown>` / `dict[str, Any]`) — read keys defensively (`Number(m.total_return ?? 0)`), it is NOT strongly typed by the schema.
- **UI primitives**: reuse `components/ui/{card,button,input,label,table}.tsx` + recharts (see `features/portfolios/DrawdownChart.tsx`/`WeightsChart.tsx` for the styled-with-tokens pattern), but **restyled toward the editorial/dense-analyst direction below** — not a default shadcn/Tailwind template.
- react-hook-form + zod (both already deps) for the form; the zod schema mirrors `BacktestSpec` (closed enums, `top_n` 1–200, `costs_bps` 0–500, `start < end`).

### Design direction — editorial / dense-analyst "tearsheet" (chosen by the user)

Results read like a **quant research tearsheet / factsheet**, not a card grid. Apply these (aim for ≥4 of the design-quality qualities, here: hierarchy via scale contrast, editorial composition, typographic character, data-as-first-class, designed states):

- **Masthead**: a strong results header — strategy label (rank_by · top_n · cadence), date range, a big headline **total return** with the benchmark + excess beside it, and a hairline rule under it. Small-caps / uppercase tracked labels.
- **Equity curve is the hero** (full-bleed within the tearsheet): strategy as the solid accent line, benchmark as a muted/dashed line, thin axes, hairline gridlines, no chartjunk. A subtle fill under the strategy line is fine; keep it restrained.
- **Metrics as a dense tabular block** (analyst factsheet): compact rows, **`tabular-nums`** + right-aligned figures, grouped (Return · Risk · vs Benchmark · Activity), hairline row separators — not one metric per card. Two/three tight columns on wide screens.
- **Typography with intent**: keep the app's body font, but give the tearsheet real hierarchy — large/condensed headline numerals, uppercase micro-labels, monospaced/tabular figures for every number. Reuse the design tokens in `globals.css`; if a display weight/feature (e.g. `font-variant-numeric: tabular-nums`) isn't tokenised, add a small utility, don't hardcode.
- **Restraint + rules**: one accent colour (semantic — green/red only for +/− return), hairline borders, generous margins around a dense core; monospace + muted for `reproducibility_hash` and the run id. Designed hover/focus/disabled/empty/loading states.
- **The setup form** stays clean + compact (a "new backtest" panel), but the tier gating reads editorially (an inline note, not a modal). The disclaimer is a small footnote/rule at the tearsheet foot.

Keep it **consistent enough** to live in the same app (same tokens, primitives, spacing scale) while clearly more editorial/dense on this surface. Avoid the banned patterns (uniform card grid, stock centered-hero, flat un-styled tables).

### The equity-curve enabler (do this first, it's the FE's data)

`compute_metrics` already has `curve`, `bench_curve`, `sessions`, `rebalance_dates` — reuse the `_exposure_series` sampling: for each rebalance date, index into `sessions` → `{as_of, strategy: _s(curve[i]), benchmark: _s(bench_curve[i])}`. Add the same guard/empty handling; extend the QV-068 exact-value unit tests with an `equity_curve` case (e.g. a monotonic curve → increasing `strategy` values). Keep every other metric byte-identical (QV-066 bias guards + QV-069 determinism compare whole `metrics` dicts within a fixed scenario — a new key is additive and, being a pure function of inputs, stays deterministic).

### Tier gating — the source of truth

`/api/v1/me` returns `entitlements: Record<string, number|boolean|null>` (auth-provider already loads it). Gate on `entitlements.backtest` (Free lacks it) and `entitlements.backtest_full` (Pro lacks it, Quant has it) — the **same two keys** QV-062 enforces server-side (`backtest`, then `backtest_full` for a >366-day range). The FE is a *mirror + UX*, never the enforcement: always let the server 403 be the backstop and render an upgrade prompt on it. If the two keys aren't present in the seeded plan entitlements, confirm with the backend seed (QV-005) before hard-coding tier names.

### Async polling

`useBacktest(id)` = `useQuery` with `refetchInterval: (q) => ['queued','running'].includes(q.state.data?.status) ? 1500 : false`. Submit via `useMutation`; on success take the returned `id` and start polling. TanStack Query is the single caching source (client already sets `no-store`). Don't hand-roll setInterval.

### Scope boundary

- **Client of the API only** (frontend-architecture memory): no business logic, no second auth, no recomputation — read metrics/curve from the response, format + chart. The one backend change is the `equity_curve` data (AC-1), nothing more.
- **Methodology page = QV-070** (not built) — QV-071 links to it + inlines the disclaimer; do not build the page here.
- **Fine-grained progress %** and the **full daily curve / result artifact** are deferred (QV-065/067) — coarse status + rebalance-sampled curve only.

### Previous-story / epic intelligence

- The backend arc is done: QV-062 (`POST/GET /backtests`, two-tier entitlement, 202/403/422), QV-065 (engine), QV-068 (metrics), QV-069 (`reproducibility_hash`). Read `backend/src/quantvista/schemas/backtest.py` for the exact request/response shape and `routes_backtests.py` for status codes.
- **QV-060 (frontend risk dashboard, PR #69)** is the closest FE precedent — recharts styled with tokens, TanStack Query, `cache: "no-store"`, colocated vitest tests, and the "flicker" lesson (hold mutation result in local state / don't unmount the results card on refetch). Reuse those patterns.
- Money is Decimal-as-string on the wire → `Number()` only at the render/chart boundary; never do money math in JS.

### Git intelligence (recent)

`0c99b69 QV-069 #78` · `00e08e0 QV-068 #77`. `features/portfolios/*` (charts + panels + tests) is the template; `lib/api/queries.ts` for hook shape; `components/app-nav.tsx` for the nav entry; `schemas/backtest.py` for the contract.

### Project context reference

`_bmad-output/project-context.md` + `frontend-architecture` memory — Next.js/TS/Tailwind/TanStack Query as the CLIENT of the FastAPI system-of-record; shadcn restyled (not template); design direction: match the existing app. Web design-quality + testing rules apply.

## Tasks / Subtasks

### Task 1: Backend — `equity_curve` in metrics (AC-1)
- [x] `analytics/backtest_metrics.py`: added `equity_curve` (strategy + benchmark sampled at rebalance dates, Decimal-string) to `compute_metrics` + `empty_metrics` (mirrors `_exposure_series`); extended `test_backtest_metrics.py`. Backend gates green; bias/determinism suites unaffected (additive key).

### Task 2: FE typed client + query hooks (AC-2)
- [x] Regenerated `openapi.json` from the FastAPI app + `npm run gen:api` (schema now has the backtest paths/types); added `useSubmitBacktest`/`useBacktest`/`useBacktests` + exported types + `SubmitBacktestError` to `lib/api/queries.ts` (poll only while `queued|running`; 403→entitlement/422→invalid).

### Task 3: Setup form + tier gating (AC-3)
- [x] `BacktestSetupForm.tsx` — gate off `entitlements` (Free → upsell card; Pro → 3M/6M/1Y presets + ≤1y client guard; Quant → custom dates); server 403 → upgrade note. **Used the repo's useState-controlled form idiom (like `AlertForm`), not react-hook-form** (see Debug Log).

### Task 4: Runner + results (AC-4, AC-5)
- [x] `BacktestWorkbench.tsx` (submit→poll, coarse queued/running/succeeded/failed) + `BacktestResults.tsx` **editorial tearsheet** (masthead headline + `EquityCurveChart.tsx` recharts strategy-vs-benchmark hero + `MetricsTable.tsx` dense grouped factsheet + `reproducibility_hash`) + inline disclaimer + Methodology link.

### Task 5: Route, nav, list (AC-6/7)
- [x] `app/(app)/backtests/page.tsx` orchestrator + `BacktestList.tsx` (past-runs ledger) + "Backtests" item in `components/app-nav.tsx`.

### Task 6: Tests + gates (AC-7)
- [x] Colocated vitest+RTL: `lib.test.ts` (helpers exact values), `BacktestSetupForm.test.tsx` (3 tiers + submit + inverted-range guard), `BacktestResults.test.tsx` (headline/factsheet/disclaimer/methodology). Frontend gates green (ESLint, `tsc`, `vitest` 94 passed, `next build`) + backend (ruff/format/mypy 278/lint-imports 3/3/pytest 763). Story → review; sprint-status → review; Dev Agent Record.

## Dev Agent Record

### Debug Log

- **Form idiom deviation (justified):** the story said react-hook-form + zod, but the repo's forms (`AlertForm`, `SaveScreenForm`) are **useState-controlled with native selects + a shared `selectClass`**. Per "write code that reads like the surrounding code", I matched that idiom — client validation (start<end, Pro ≤1y) inline, the server the backstop. rhf/zod are deps but unused for forms here; introducing them would've been inconsistent.
- **Equity curve was the missing data:** QV-068 kept `metrics` scalar, so "equity curve vs Nifty200" had no series. Added a compact `equity_curve` (sampled at rebalance dates, Decimal-string) — the ONE backend change, in the same shape as `exposure_series`, no API/schema change.
- **openapi-fetch nullable payload:** the envelope's `data.data` is typed nullable → guarded `!data?.data` in the three hooks so they return a non-null `Backtest`/list (matches how the page/workbench narrow `bt`).
- **recharts v3 Tooltip formatter** is stricter than v2 — used the single-arg `(v) => …` form (like `DrawdownChart`).
- Tearsheet redundancy: total return appears in the masthead headline AND the factsheet (intentional for a factsheet) — the test uses `getAllByText`.
- **Misleading submit error (fixed, found in manual QA):** a valid 17–31 Jul spec surfaced "That backtest spec was rejected — check the inputs". The spec was fine; the API returned **404**. `useSubmitBacktest` already mapped 404→`unknown`, but the form collapsed `unknown` and `invalid` into the same input-blaming copy. Extracted `submitErrorMessage()` so **only a real 422 blames the inputs**; unreachable/5xx/network now says "Couldn't reach the backtest service. Your inputs look fine." Regression-tested.
  - Root cause of the 404 was environmental, not code: the dev uvicorn on :8000 had been started **without `--reload` on 2026-07-26**, predating QV-062 (2026-07-27) — so `/api/v1/backtests` didn't exist on the running app. Restarted with `--reload`; also started the missing **Celery worker** (`-Q user`), without which a submitted run sits at `queued` forever. Same trap as [[sentiment-service-architecture]].
- **Writes committed *after* the response was sent (fixed for these routes; app-wide issue flagged):** deleting a run left it visible in the history. Root cause is not the FE cache — FastAPI (0.137) runs a `yield`-dependency's exit code **after the response is sent**, and `get_tenant_session` commits there (`session_scope`). So a client that refetches the instant it sees `204` reads pre-commit state. Reproduced on the live server: submit → immediate `GET {id}` 404'd **5/5** in a tight loop, and passed once slowed down — a genuine timing race. `submit`/`delete` now `session.commit()` before returning (and submit commits *before* `enqueue`, closing a second race where a fast worker could read the row by id before it existed). Two tests pin the ordering via an independent connection. **Now fixed app-wide** (initially only the backtest routes were patched; the user rightly pushed back on shipping a known bug in four other places). `CommitBeforeResponseRoute` (`api/route_class.py`) commits the request-scoped session inside the route handler — Starlette awaits the handler for the `Response` and only *then* sends it, so the ordering is well-defined and version-independent, unlike the dependency exit stack. `get_tenant_session` parks the session on `request.state`; the route class is applied to all five tenant-session routers (alerts, backtests, notifications, portfolios, screens). Reads are skipped (`GET/HEAD/OPTIONS`), and `submit_backtest_endpoint` keeps its explicit commit because it must publish its Celery task *after* the row exists, which happens inside the handler. Auth routes were never affected — `AuthService` opens and commits its own `session_scope` inside the endpoint. **Measured on the live server:** screens 1/6 stale without the route class → 0/12 with it; screens/portfolios/alerts/backtests all 6/6 consistent after. `tests/test_commit_before_response.py` is a permanent structural guard that enumerates tenant-session routes and names any write route missing the class (verified to fail when the class is removed).
- **Methodology link was a dead end (fixed):** `/methodology` does not exist (QV-070, Epic 10) and Next served its bare default 404, which reads as an empty page. Link removed until the page ships; the disclaimer was already written to be self-contained, so the tearsheet loses nothing. Not authoring the copy here on purpose — the methodology/disclaimer content is deliberately scoped to Epic 10 (QV-011 draft → QV-070 page) for compliance review.
- **`reproducibility_hash` removed from the UI (AC-5 deviation, deliberate):** the footer showed a bare `repro <hex>…`, which the user flagged as meaningless on a research surface. It was first relabelled `recipe …` with an explanatory tooltip, then dropped from the tearsheet entirely: it is an **audit artifact** that only carries meaning when comparing two runs. It is still computed, persisted in `metrics`, and returned by the API, so provenance and run-to-run comparison are unaffected — only the rendering is gone. AC-5 asks for it "shown small/monospace"; restoring it is one element. The footer is now the centred disclaimer alone.
- **Equity curve contradicted the headline (fixed, found in manual QA):** sampling *only* rebalance dates ended the series before the run did — a real run charted `+4.7%` at its last point (2026-07-01) under a `-0.67%` headline `total_return` (measured to the last session, 2026-07-31). `_equity_curve` now appends the **final session** as a terminal point (de-duped when the last rebalance already is the last session). Verified end-to-end: curve last − 1 == `total_return`, and the same for the benchmark.
- **Results were unreachable + lost on refresh (fixed, found in manual QA):** the active run id lived in `useState` inside `BacktestWorkbench`, and `BacktestList` rows were plain `<div>`s. So a refresh discarded a finished tearsheet (forcing a re-run) and a succeeded past run could not be opened at all. Moved the selection to **URL state** (`?run=<id>`, new `useSelectedRun` hook) per the repo's "URL as state" rule — the page now survives reload, history rows are `<button>`s that open any run, the open row is marked `aria-current`, and a run is linkable. `useSearchParams` is wrapped in `<Suspense>` so `/backtests` stays statically prerendered. Also surfaced the poll's error branch ("Could not load that backtest") instead of showing a perpetual spinner.
- **Default range was guaranteed-empty (fixed):** the Quant custom range defaulted to a hardcoded `2020-01-01 → 2020-12-31`, entirely outside the ingested price history — the first run any Quant user made returned all-zero metrics and a flat curve. Now defaults to a trailing year (`presetRange(12)`).
- **Producer/worker queue-routing mismatch (fixed — real bug, not just local config):** a submitted backtest sat at `queued` forever. Celery applies `task_routes` in the **producer** at publish time, but the table lived only on `jobs.celery_app`; the API's `core.tasks._producer()` was a bare client, so `enqueue("quantvista.run_backtest", …)` published to the default `celery` queue while `worker -Q user` idled (verified: `llen celery`=1, `llen user`=0). Moved `TASK_ROUTES`/`TASK_DEFAULT_QUEUE` into `core.tasks` (foundation — `jobs` may import `core`, never the reverse) and had both ends read the one table. Two regression tests pin producer/worker agreement and assert the published routing key is `user`; both fail on the pre-fix code (`- user + celery`).
- **Flaky integration test (fixed):** `test_deliver_notifications.py::test_email_channel_uses_sender_and_is_honored` asserted `spy.sent == [emails[0]]` — a **global** equality on a deliberately **cross-tenant** job (`deliver_pending`). The dev DB carries a real daily-firing alert rule for the owner's account, so any run after that day's alert fired swept a foreign recipient into the spy. Added `_SpySender.sent_to(emails)` to scope both asserts to the test's own seeded users (also fixes the same latent bug in the retry test). Verified by seeding a synthetic orphan pending event → suite green → probe removed.

### Completion Notes List

- **Finishes Epic 8** — the backtest UI: tier-gated setup (Free/Pro-1y/Quant), async submit→poll (TanStack Query `refetchInterval` only while running), and an **editorial/dense-analyst tearsheet** — masthead headline, equity-vs-benchmark hero chart, dense grouped metrics factsheet (`tabular-nums`, hairline rows, +/- semantic colour), `reproducibility_hash`, disclaimer + Methodology link. Direction per [[design-direction-editorial-analyst]].
- **Pure client of the API** — no business logic; reads metrics/curve from the response, `Number()` only at the render boundary. One tiny backend enabler (the `equity_curve` series).
- **Honest scope:** coarse progress (fine-grained % deferred, QV-065); rebalance-sampled curve (daily → artifact, QV-067); `/methodology` link is graceful until QV-070 ships.
- Gates green both sides; frontend 94 tests / backend 763 passed.

### File List

- `backend/src/quantvista/analytics/backtest_metrics.py` (modified — `equity_curve` in `compute_metrics`/`empty_metrics`)
- `backend/tests/test_backtest_metrics.py` (modified — equity_curve tests)
- `frontend/src/lib/api/openapi.json` (regenerated), `frontend/src/lib/api/schema.d.ts` (regenerated)
- `frontend/src/lib/api/queries.ts` (modified — backtest hooks + types + `SubmitBacktestError`)
- `frontend/src/features/backtests/lib.ts` + `lib.test.ts` (new)
- `frontend/src/features/backtests/BacktestSetupForm.tsx` + `.test.tsx` (new)
- `frontend/src/features/backtests/EquityCurveChart.tsx` (new)
- `frontend/src/features/backtests/MetricsTable.tsx` (new)
- `frontend/src/features/backtests/BacktestResults.tsx` + `.test.tsx` (new)
- `frontend/src/features/backtests/BacktestWorkbench.tsx` (new)
- `frontend/src/features/backtests/BacktestList.tsx` (new)
- `frontend/src/app/(app)/backtests/page.tsx` (new)
- `frontend/src/components/app-nav.tsx` (modified — Backtests nav item)
- `backend/tests/integration/test_deliver_notifications.py` (modified — scope the cross-tenant spy asserts to the test's own recipients)
- `backend/src/quantvista/core/tasks.py` (modified — shared `TASK_ROUTES`/`TASK_DEFAULT_QUEUE` + `queue_for`; producer now routes)
- `backend/src/quantvista/jobs/celery_app.py` (modified — reads the shared routing table)
- `backend/tests/test_celery_app.py` (modified — producer/worker routing-agreement regressions)
- `frontend/src/features/backtests/useSelectedRun.ts` + `.test.tsx` (new — `?run=<id>` URL state)
- `frontend/src/features/backtests/BacktestList.test.tsx` (new — clickable rows + delete)
- `backend/src/quantvista/analytics/backtests.py` (modified — `delete_backtest`, RLS-scoped)
- `backend/src/quantvista/api/routes_backtests.py` (modified — `DELETE /backtests/{id}` 204/404 + commit-before-response)
- `backend/tests/integration/test_api_backtests.py` (modified — delete, isolation, commit-ordering)
- `frontend/src/features/backtests/deleteBacktest.integration.test.tsx` (new — delete refreshes the list)
- `backend/src/quantvista/schemas/backtest.py` (modified — `custom_basket` type + `symbols`)
- `backend/src/quantvista/analytics/backtest.py` (modified — `_picks` selection seam)
- `backend/src/quantvista/analytics/backtest_data.py` (modified — `basket_ids`)
- `backend/src/quantvista/market_data/repositories.py` (modified — `stock_ids_by_symbol`)
- `frontend/src/features/backtests/SymbolPicker.tsx` + `.test.tsx` (new — basket search/pick)

### Added after review (user-requested)

- **Custom-basket backtests** — a second strategy type alongside the factor strategy, folded into this PR at the user's request (initially planned as a separate story). `BacktestSpec.type` opens to `factor_strategy | custom_basket`; a basket carries `symbols` (1–50, upper-cased/trimmed/de-duped in the validator so the reproducibility hash does not depend on typing), and `symbols` is required by — and exclusive to — a basket (a factor strategy that passed symbols would otherwise look honoured but be ignored). `rules.top_n` gained a default so a basket need only choose a cadence. The engine's selection is now one seam (`_picks`): a basket resolves its names **once** and holds them throughout; the ranker is never consulted. PIT survives untouched — the existing "only weight names priced on this date" filter means a not-yet-listed or delisted pick is simply not held. `BacktestDataAccess.basket_ids` raises on an unknown symbol rather than quietly holding fewer names than asked. UI: a strategy toggle that swaps rank_by/top_n for a debounced `SymbolPicker` (server-side search over the whole universe, chips for picks, capped at 50). Verified end-to-end on real data — a 3-name basket returned +51.97% vs the index's +4.77%, 100% exposure, 5% turnover, beta 1.35.

- **Delete a run** — `DELETE /api/v1/backtests/{id}` (204; RLS makes a foreign id 404, and a second delete 404s) + an always-visible `Trash2` icon button per history row, matching the `PortfolioList` precedent, with an **inline confirm** (delete is irreversible). Deleting the open run closes the tearsheet first so the URL never points at a missing row. Allowed at any status — the job's `mark_running` guard already no-ops on a deleted row.

### Known data limitation (dev box, not a code defect)

`daily_prices` spans **2025-06-02 → 2026-07-24** (286 sessions). A short window like 17–31 Jul 2026 has only 6 sessions and, at monthly cadence, yields a degenerate run. Use a range inside the ingested span. The tearsheet renders empty/degenerate runs gracefully (AC-5).

**Indicator backfill was required (done 2026-07-31).** `technical_indicators` only covered 2026-07-07 → 2026-07-24 (7 days), and the engine ranks off `compute_universe`, which reads that snapshot. So *every* rebalance date before 2026-07-07 selected **0** names → 0% exposure and an all-zero strategy column while the benchmark (pure price maths) still computed — the reported "all params are 0". Backfilled all 286 sessions via `quantvista.compute_indicators` (138s, 0 failures); all 13 rebalance dates of the reference run now select 20 names and the tearsheet is fully populated (total return −0.67%, exposure 90.1%, Sharpe 0.12, beta 0.84, 13 rebalances). **Any fresh environment needs this backfill before backtests mean anything.**

### Change Log

- 2026-07-29 — QV-071 backtest UI (finishes Epic 8): editorial/dense-analyst tearsheet (tier-gated setup form + async poll + equity-curve-vs-benchmark chart + dense metrics factsheet + reproducibility hash + disclaimer/methodology). One backend enabler: `equity_curve` series in metrics. Frontend gates green (94 tests), backend 763 passed.

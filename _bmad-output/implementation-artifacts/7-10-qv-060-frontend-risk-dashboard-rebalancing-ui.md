---
baseline_commit: 66667ddfa31ee7bcd22e391dc409c0702cdf2eaa
---

# Story 7.10: QV-060 — Frontend: Risk dashboard + rebalancing UI

Status: done

**Epic:** EPIC-PORT (Epic 7) · **Points:** 8 · **Depends:** QV-058 (RiskEngine + `GET /portfolios/{id}/risk`), QV-059 (`POST /portfolios/{id}/rebalance`), QV-056 (FE portfolio builder + optimize UI)

> **Scope note:** primarily `[FE]`, but carries a small `[BE]` addition (expose the already-computed drawdown series on `/risk`) so the drawdown-over-time chart is real — decided with {user_name}. Also implements **both** apply-to-targets surfaces (optimizer → targets, and rebalance → targets).

## Story

As a user, I want to monitor portfolio risk and act on rebalancing, so portfolio management is closed-loop (build → optimize → **monitor risk → rebalance**).

## Acceptance Criteria

0. **Backend: expose the drawdown series** (Task 0, before the client refresh) — `RiskEngine._series_metrics` already computes the full dated drawdown array (`equity`/`drawdowns`, `risk.py:174-177`) and discards all but the scalar. Surface it: add `drawdown_series` to `RiskMetrics`, thread `ReturnsMatrix.dates` through, add `DrawdownPointDTO { date: str, value: str }` + `drawdown_series: list[DrawdownPointDTO]` to `RiskResponse`, map it in the route. Values are Decimal-strings ≤ 0 (drawdown magnitude as a signed/zero fraction); `min(value) == -max_drawdown` (invariant to assert). No migration. Unit + integration tests.
   [Source: `risk.py:174-177`; `ReturnsMatrix.dates`]

1. **Typed client refreshed (Task 1)** — the checked-in `frontend/src/lib/api/openapi.json` is **stale**: it has `/portfolios/{id}/optimize` but **not** `/risk` or `/rebalance`. After the Task-0 backend change, re-dump `create_app().openapi()` → `openapi.json`, then `npm run gen:api` → `schema.d.ts` exposes `RiskResponse` (incl. `drawdown_series`), `BetaCoverageDTO`, `DrawdownPointDTO`, `RebalanceRequest`, `RebalanceResponse`, `TradeSuggestionDTO`. Every new hook is typed off these generated types — **no hand-written request/response types** (project rule: contract-first).
   [Source: `04` §3.5; QV-040 Task 0 precedent]

2. **Risk dashboard** on the portfolio detail page (`/portfolios/[id]`) — from `GET /portfolios/{id}/risk`:
   - Metric tiles: **beta, annualized volatility, Sharpe, Sortino, max drawdown, HHI (concentration)**. Each backend value is a **Decimal-string or `null`** → render `—` on `null`; format ratios/vol as `%` where appropriate, beta/Sharpe/Sortino as plain numbers, HHI as a 0–1 concentration figure.
   - **Sector exposure** rendered as a Recharts bar chart from `sector_exposure` (`dict[str, str]`, sector → Decimal-string weight), sorted desc, `%`-formatted.
   - **Beta coverage** note (`beta_coverage.covered/total`) so the user sees how many holdings had a usable beta.
   - `as_of_date` shown; research-not-advice **disclaimer** rendered (endpoint sets the header + `meta.disclaimer`).
   - States: loading; **422** (no positions → "Add holdings first"; no price data → "No price data yet"); **404** (surfaced by the page's existing not-found path). No paid gate — risk is available to any authenticated owner.
   [Source: `04` §3.5; `05` §1.3; RiskResponse schema]

3. **Drawdown-over-time chart** — render a real drawdown chart from the new `drawdown_series` (AC 0): a Recharts area/line over `{ date, value }` (value ≤ 0, `%`-formatted, filled below zero), with the trough annotated as the max drawdown. Empty/thin history (series absent or too short) → a graceful "not enough history" state.
   [Source: AC 0 `drawdown_series`]

4. **Rebalancing panel** — from `POST /portfolios/{id}/rebalance` with body `{ drift_threshold }` (default `0.05`):
   - `drift_threshold` input (decimal, 0–1); a **"Check drift"** action runs the mutation.
   - Shows **total_drift** (`%`), a **needs_rebalance** badge (on-plan vs drift-exceeds-threshold), and a **trades table**: symbol · direction (**buy/sell**, tone-colored) · current_weight · target_weight · delta_weight — all Decimal-strings, `%`-formatted, sorted as returned (largest |delta| first).
   - Empty `trades` with `needs_rebalance=false` → "On plan — no trades needed."
   - **422** handling: no target weights set → a clear "Set target weights (run optimize first)" message; no positions / no price data → matching messages.
   - Disclaimer rendered. No paid gate.
   [Source: `04` §3.5; RebalanceResponse schema]

5. **Apply-to-targets — BOTH surfaces** (shared `useApplyTargets`, one `PUT /portfolios/{id}/positions/{stock_id}` per name, then invalidate positions + risk + rebalance). Confirm-before-apply; each does **not** execute trades (no brokerage, D1 non-advice):
   - **Optimizer → targets** ("Set as targets" on the `OptimizePanel`/`WeightsChart` result): writes the optimizer's suggested `weights` as each position's `target_weight`. This closes the loop (optimize → set targets → monitor drift).
   - **Rebalance → targets** ("Apply targets" on the rebalance panel): writes each suggested trade's normalized `target_weight` back onto the position (persists the plan's normalization).
   [Source: sprint-07 QV-060 "apply-to-targets" (both, per {user_name}); `useUpsertPosition` exists]

6. **Method selector honors tier** — the optimize **method** selector (mean-variance / risk-parity) already exists in `OptimizePanel` (QV-056/057); risk-parity is Pro-gated **server-side** (403 → `limit` → upgrade CTA, already handled). This story keeps that behavior intact and does not regress it. No new tier logic for risk/rebalance (both are un-gated).
   [Source: OptimizePanel.tsx; QV-057]

7. **Tests** — Vitest component/unit tests for the new pieces (risk tile formatting incl. `null→—`, sector-chart data mapping, rebalance trades rendering + buy/sell tone, apply-targets calls PUT per trade) + a Playwright e2e extension that navigates to a portfolio, sees the risk metrics + rebalance panel. Frontend gates green: `eslint`, `tsc --noEmit`, `vitest`, `next build`.
   [Source: web testing rules; QV-056 test precedent]

---

## Dev Notes

### Architecture & conventions (FE)

- **Client of the FastAPI system-of-record** (see [[frontend-architecture]]): Next.js App Router + TS + Tailwind v4 + shadcn/ui + TanStack Query + Recharts. **No** hand-written API types — everything is generated via `openapi-typescript`. No business logic duplicated from the backend; the FE only renders + orchestrates calls.
- **Decimal discipline on the wire**: every money/ratio/weight from these endpoints is a **string** (never a JS number in transit). Parse to `Number(...)` only for chart math / display formatting, exactly like `OptimizePanel.asPct` and `WeightsChart.pct`. Never send a float back — `PUT positions` takes `target_weight` as a string.
- **Feature folder**: `frontend/src/features/portfolios/` (existing: `PortfolioBuilder`, `OptimizePanel`, `PositionsEditor`, `WeightsChart`, `PortfolioList`). Add the new surfaces here.
- **Design**: reuse the established Swiss/shadcn tokens + `Card`, `Button`, `Input`, `Label`, `Disclaimer`. Match `OptimizePanel`'s visual grammar (metric label = `text-xs text-muted-foreground`, value = `font-medium tabular-nums`). Do **not** introduce a new design language.

### Task 1 — refresh the typed client (right after the Task-0 backend change)

Same mechanism QV-034/QV-040 established — **no running server needed**:
```bash
cd backend && source .venv/bin/activate
python -c "import json; from quantvista.api.app import create_app; print(json.dumps(create_app().openapi()))" \
  > ../frontend/src/lib/api/openapi.json
cd ../frontend && npm run gen:api   # openapi-typescript openapi.json -o schema.d.ts
```
After this, `components["schemas"]` exposes `RiskResponse` (incl. `drawdown_series`), `BetaCoverageDTO`, `DrawdownPointDTO`, `RebalanceRequest`, `RebalanceResponse`, `TradeSuggestionDTO`, and the paths `/api/v1/portfolios/{portfolio_id}/risk` (GET) + `/api/v1/portfolios/{portfolio_id}/rebalance` (POST) exist in the typed client. **Every Task-2 hook depends on this.**

Note (QV-079): `create_app().openapi()` works because default `app_env` is `local` (docs/openapi are only disabled when `app_env == "production"`).

### Backend change (Task 0) — `drawdown_series` on `/risk`

The series already exists in `RiskEngine._series_metrics` (`portfolio/risk.py`):
```python
equity = np.concatenate([[1.0], np.cumprod(1.0 + r_p)])      # T+1 points
drawdowns = equity / np.maximum.accumulate(equity) - 1.0      # ≤ 0, aligned to equity
max_dd = float(-drawdowns.min())                              # currently the only thing kept
```
- Thread dates in: `metrics()` receives the `ReturnsMatrix` (has `dates: tuple[date,...]`, length T). The equity/drawdown arrays are length **T+1** (a leading NAV=1 point). Date the series as `[dates[0], *dates]` (or drop the leading point and return the T dated drawdowns — pick one and assert length in the test). Keep it simple: return the **T+1** points dating the leading one to the first return date, or return the T points aligned to `dates` (recommended: align to `dates`, i.e. drop the seed point, so every point has a real trading date).
- `RiskMetrics` gains `drawdown_series: tuple[tuple[date, Decimal], ...] | None` (None when history is too thin — same guard as the scalar metrics).
- `schemas/risk.py`: add `class DrawdownPointDTO(BaseModel): date: str; value: str` and `drawdown_series: list[DrawdownPointDTO]` on `RiskResponse` (Decimal-as-string; **response DTO → no `extra="forbid"`**).
- Route (`routes_portfolios.py` risk handler): map `metrics.drawdown_series` → `[DrawdownPointDTO(date=d.isoformat(), value=str(v)) for d, v in …]` (empty list when None).
- **Invariant test:** `min(value for _,value in series) == -max_drawdown` (when series non-empty); series values all ≤ 0; length matches the dated returns. Add an integration assertion that the endpoint returns a non-empty `drawdown_series` for a seeded multi-day portfolio.
- **Preserve:** the scalar `max_drawdown` field and every existing risk field/behaviour — this is purely additive. `risk_snapshots` persistence is unchanged (don't persist the series).

### Backend contracts (authoritative — do not re-derive)

**`GET /api/v1/portfolios/{id}/risk`** → `Envelope<RiskResponse>` (`routes_portfolios.py:315`). Auth-only, tenant-scoped (unknown/foreign → **404** `PortfolioNotFound`). `OptimizeError` → **422 `validation_error`** when no positions ("…no positions to assess") or no price data. Disclaimer header + `meta.disclaimer`.
```
RiskResponse = {
  as_of_date: string
  beta: string | null
  volatility: string | null
  max_drawdown: string | null
  sharpe: string | null
  sortino: string | null
  hhi: string                              // always present
  sector_exposure: { [sector: string]: string }   // Decimal-string weights
  beta_coverage: { covered: number; total: number; ratio: string }
  drawdown_series: { date: string; value: string }[]   // NEW (Task 0); value ≤ 0, [] when thin
}
```

**`POST /api/v1/portfolios/{id}/rebalance`** → `Envelope<RebalanceResponse>` (`routes_portfolios.py:387`). Body `RebalanceRequest = { drift_threshold: string }` (default `"0.05"`, 0–1). Auth-only, tenant-scoped (**404**). **422** when no positions / no price data / **no target weights set** ("no target weights set; run /optimize first…"). Disclaimer.
```
RebalanceResponse = {
  as_of_date: string
  total_drift: string            // Σ|Δw|/2, 0..0.5
  needs_rebalance: boolean        // total_drift > drift_threshold
  trades: TradeSuggestionDTO[]    // sorted desc by |delta_weight|
}
TradeSuggestionDTO = {
  stock_id: string; symbol: string; direction: "buy" | "sell"
  current_weight: string; target_weight: string; delta_weight: string  // signed, +=buy
}
```

### Existing hooks to reuse (`src/lib/api/queries.ts`)

- `usePortfolio(id)`, `usePositions(portfolioId)` — already power the detail page.
- **`useUpsertPosition(portfolioId)`** (line 413) — `PUT /portfolios/{id}/positions/{stock_id}` with `UpsertPositionRequest` body; invalidates `["positions", portfolioId]`. **This is the apply-to-targets primitive** — call it once per suggested trade with `{ target_weight: trade.target_weight }`.
- `useOptimize(portfolioId)` + `OptimizeError` (kind: `limit|infeasible|invalid|unknown` from status 403 / `code==="infeasible"` / 422) — **mirror this exact error-classification pattern** for the new hooks.
- `envelopeMessage(error)` helper for extracting the envelope error message.
- `useAuth()` → `user.entitlements` (keys seen: `optimization`, `alerts`, `portfolios`). Risk/rebalance need **no** entitlement.

### New hooks to add (typed off the regenerated schema)

- **`useRisk(portfolioId)`** — `useQuery(["risk", portfolioId], api.GET("/api/v1/portfolios/{portfolio_id}/risk", …))` → `data.data` (`RiskResponse`). Return the query so the component can branch on `isLoading` / status 422 / 404. Classify 422 vs 404 like `stockDetailQuery` narrows `response.status`.
- **`useRebalance(portfolioId)`** — `useMutation` over `POST …/rebalance` with `{ drift_threshold: string }`; throw a typed `RebalanceError { kind: "no_targets" | "invalid" | "unknown" }` (map 422 whose message mentions targets → `no_targets`, other 422 → `invalid`). Mirror `useOptimize`.
- **`useApplyTargets(portfolioId)`** — `useMutation` that takes `TradeSuggestionDTO[]`, `await Promise.all(trades.map(t => api.PUT(positions, { path:{portfolio_id, stock_id:t.stock_id}, body:{ target_weight: t.target_weight } })))`, then `qc.invalidateQueries` for `["positions",id]`, `["risk",id]`. Surface a partial-failure error if any PUT fails.

### New components (`src/features/portfolios/`)

- **`RiskDashboard.tsx`** — `{ portfolioId }`. Uses `useRisk`. Metric tiles + `SectorExposureChart` + beta-coverage + disclaimer + empty/422 states.
- **`SectorExposureChart.tsx`** — Recharts `BarChart` over `Object.entries(sector_exposure)` mapped to `{ sector, pct: Number(w)*100 }`, sorted desc. Mirror `WeightsChart`'s Recharts setup (`ResponsiveContainer`, `Bar`, `XAxis/YAxis`, `Tooltip`).
- **`RebalancePanel.tsx`** — `{ portfolioId, hasHoldings }`. `drift_threshold` `Input`, "Check drift" button (`useRebalance`), results (total_drift, needs_rebalance badge, trades table), **"Apply targets"** button (`useApplyTargets`, confirm dialog), 422/empty states, disclaimer. Mirror `OptimizePanel` structure/error rendering.

### Wiring into the page

Mount both under the existing `/portfolios/[id]` page. Preferred: extend `PortfolioBuilder.tsx` with two new full-width sections ("Risk" + "Rebalance") **below** the existing Holdings/Optimize grid — keeps one detail surface. Alternatively add a lightweight tab strip (Builder | Risk | Rebalance) if the page gets long; **do not** add a new route. Reuse `PortfolioBuilder`'s `usePositions` result to pass `hasHoldings`.

### Previous-story intelligence

- **QV-056 (portfolio builder + optimize UI)** established every pattern you need: typed hooks, `OptimizePanel` error-kind classification, `WeightsChart` Recharts usage, Disclaimer placement, tier gating via `user.entitlements.optimization`. **Follow it closely.**
- **QV-040 (screener/compare)** established the **Task-0 client refresh** (`app.openapi()` dump → `gen:api`) — the exact same stale-client situation applies here.
- **QV-058/059** are the backend this consumes — already merged; contracts above are final (no backend change expected in this story).
- **QV-079 (just merged)**: `extra="forbid"` is on request bodies — `RebalanceRequest` rejects unknown fields, so send **only** `drift_threshold`. Rate limiting is OFF by default (no dev impact).

### Git intelligence (recent commits)

`66667dd` QV-079 security hardening · `a25f4e3` QV-059 rebalance+drift · `300b5f6` QV-058 RiskEngine · `9cef731` QV-057 risk-parity · `60d3994` QV-056 portfolio builder+optimize UI. The FE portfolio surface and both backend endpoints are all in `master` now — this is pure FE integration, **no migration, no backend change**.

### Testing

- **Vitest** (mirror `OptimizePanel.test.tsx`): risk tile formatting (`"0.1234"→"12.34%"`, `null→"—"`), `SectorExposureChart` data mapping + sort, `RebalancePanel` trades rendering (buy/sell tone, `%` format), `useApplyTargets` issues one PUT per trade with the right `target_weight`. Keep component tests light where visual-regression carries more signal.
- **Playwright** (extend `e2e/dashboard.spec.ts` or a new `e2e/portfolio.spec.ts`): register → create portfolio → add a holding → open detail → assert the Risk section renders (metric labels visible) and the Rebalance panel is present. Deterministic waits, no arbitrary timeouts.
- **Backend (Task 0)**: TDD the `drawdown_series` addition (RED unit+integration first). Run the full-tree backend gates before push: `ruff check . && ruff format --check . && mypy && lint-imports && bandit -c pyproject.toml -r src/ -ll -q && pip-audit --skip-editable && pytest`.
- Run before push: `cd frontend && npm run lint && npx tsc --noEmit && npm test && npm run build`. Both backend + frontend CI jobs will run (this PR touches `backend/**` and `frontend/**`).

### Project context reference

See `_bmad-output/project-context.md`: contract-first (generated client, never hand-written types), standard envelope `{success,data,error,meta}`, canonical error codes (422 `validation_error`, 403 `forbidden`/`entitlement_exceeded`), Decimal-as-string for money, research-not-advice disclaimer on every research-output surface (D1). Related memory: [[frontend-architecture]], [[portfolio-weight-basis]], [[price-targets-roadmap]].

---

## Tasks / Subtasks

### Task 0: Backend — expose `drawdown_series` on `/risk`  `[BE]`
- [x] 0a. RED: 3 unit tests (dated series; `min == -max_drawdown`; None when dates absent / thin) + 1 integration test (`/risk` returns non-empty dated series, trough == −max_drawdown)
- [x] 0b. `RiskMetrics.drawdown_series` (default None); `_series_metrics` returns `(scalars, series)` — builds the dated series from the already-computed `drawdowns[1:]` zipped to `returns.dates` (guarded: only when `len(dates)==T`, else None)
- [x] 0c. `schemas/risk.py`: `DrawdownPointDTO {date,value}` + `RiskResponse.drawdown_series`; risk route maps `metrics.drawdown_series or ()` → list. Purely additive; scalar `max_drawdown` + all fields preserved; no migration
- [x] 0d. Backend gates green: ruff/format/mypy(251)/lint-imports(3/3)/bandit(0)/pip-audit(0); **661 passed / 5 skipped**

### Task 1: Refresh the typed API client
- [x] 1a. Dump `create_app().openapi()` → `frontend/src/lib/api/openapi.json` (command in Dev Notes); confirm `/risk` (with `drawdown_series`) + `/rebalance` present
- [x] 1b. `npm run gen:api`; confirm `RiskResponse`, `BetaCoverageDTO`, `DrawdownPointDTO`, `RebalanceRequest`, `RebalanceResponse`, `TradeSuggestionDTO` exported

### Task 2: API hooks (typed off generated schema)
- [x] 2a. Export types from `queries.ts`
- [x] 2b. `useRisk(portfolioId)` — query; loading / 422 / 404 branches
- [x] 2c. `useRebalance(portfolioId)` — mutation + typed `RebalanceError` (`no_targets` | `invalid` | `unknown`), mirroring `useOptimize`
- [x] 2d. `useApplyTargets(portfolioId)` — takes `{stock_id, target_weight}[]`; bulk `PUT` per name; invalidate `["positions",id]` + `["risk",id]` (used by BOTH apply surfaces)

### Task 3: Risk dashboard
- [x] 3a. `SectorExposureChart.tsx` — Recharts bar chart from `sector_exposure` (sorted desc, `%`)
- [x] 3b. `DrawdownChart.tsx` — Recharts area/line over `drawdown_series` (`%`, ≤ 0, trough = max drawdown; thin-history empty state)
- [x] 3c. `RiskDashboard.tsx` — metric tiles (beta/vol/sharpe/sortino/max-drawdown/HHI, `null→—`) + sector chart + drawdown chart + beta-coverage + disclaimer + empty/422 states
- [x] 3d. Vitest: tile formatting (incl. `null`), sector mapping/sort, drawdown mapping (dates + `%`, empty)

### Task 4: Rebalancing panel + apply-to-targets (rebalance side)
- [x] 4a. `RebalancePanel.tsx` — drift_threshold input, "Check drift", total_drift + needs_rebalance badge, trades table (buy/sell tone, `%`), disclaimer
- [x] 4b. 422/empty states ("set targets — run optimize first", "on plan — no trades", no price data)
- [x] 4c. "Apply targets" — confirm → `useApplyTargets(trades→{stock_id,target_weight})` → invalidate; disabled with no trades
- [x] 4d. Vitest: trades render + tone; apply issues one PUT per trade with the correct `target_weight`

### Task 5: Apply-to-targets (optimizer side)
- [x] 5a. "Set as targets" on the optimize result (`OptimizePanel`/`WeightsChart`): map optimizer `weights` → `{stock_id, target_weight}[]` → `useApplyTargets`; confirm + invalidate; disabled without a result
- [x] 5b. Vitest: optimizer weights map to one PUT per name with the right `target_weight`

### Task 6: Wire into the portfolio detail page
- [x] 6a. Add "Risk" + "Rebalance" sections to `PortfolioBuilder.tsx` (full-width, below the builder grid); pass `hasHoldings` from `usePositions`
- [x] 6b. Confirm the optimize **method selector** tier behavior is unchanged (risk-parity 403 → upgrade CTA)

### Task 7: E2E + green gates + sprint status
- [x] 7a. Playwright: portfolio detail shows Risk metrics + drawdown/sector charts + Rebalance panel (deterministic)
- [x] 7b. Frontend: `npm run lint && npx tsc --noEmit && npm test && npm run build` — green
- [x] 7c. Update `sprint-status.yaml` → review; fill Dev Agent Record

---

## Dev Agent Record

### Debug Log

- **Legacy unit-test compat:** the existing `test_risk_engine._returns` helper builds `ReturnsMatrix(dates=())`. So `_series_metrics` guards the series build on `len(returns.dates) == T` and returns `None` otherwise — old tests keep passing (series None), production (real dates from `returns_matrix_as_of`) gets the series.
- **Envelope nullability:** the generated `data.data` is `T | null` even after the `error`/`!data` guard — with an explicit `Promise<RiskResponse>`/`Promise<RebalanceResponse>` return type, tsc flagged it. Fixed by guarding `!data?.data` (narrows to non-null).
- **Query data narrowing:** TanStack Query doesn't narrow `data` to defined from `isError`/`isLoading` flags — added an explicit `if (!r) return null` in `RiskDashboard` before using `risk.data`.
- **Test text ambiguity:** `25.00%` appears as both drift and a weight → used `getAllByText`. `window.confirm` stubbed with `vi.spyOn(window,"confirm")` for the apply-targets tests.

### Completion Notes List

- **Backend (Task 0):** `drawdown_series` on `/risk` — the dated series was already computed inside `_series_metrics` and discarded; now `_series_metrics` returns `(scalars, series)`, `RiskMetrics.drawdown_series` carries it (dated to `returns.dates`, dropping the seed NAV point so `min == -max_drawdown`), `DrawdownPointDTO` + `RiskResponse.drawdown_series` expose it, the route maps `metrics.drawdown_series or ()`. Purely additive; scalar `max_drawdown` + all fields preserved; **no migration**.
- **Typed client (Task 1):** re-dumped `create_app().openapi()` → `openapi.json` (now has `/risk` + `/rebalance` + `drawdown_series`), `npm run gen:api`.
- **Hooks (Task 2):** `useRisk` (query; typed `RiskError` no_data/not_found), `useRebalance` (mutation; typed `RebalanceError`, 422-mentions-target → `no_targets`), `useApplyTargets` (bulk PUT per name, invalidates positions+risk) — shared by both apply surfaces. Pure formatting/mapping extracted to `lib/risk.ts` (8 unit tests).
- **Risk dashboard (Task 3):** metric tiles (beta/vol/Sharpe/Sortino/max-dd/HHI, `null→—`), `SectorExposureChart` (Recharts bar), `DrawdownChart` (Recharts area, ≤0, thin-history state), beta-coverage + disclaimer + loading/422/404 states.
- **Rebalance (Task 4):** `RebalancePanel` — drift input, total_drift + needs_rebalance badge, buy/sell trades table (tone), 422 no_targets → "run optimize first", "Apply targets" (confirm → bulk PUT).
- **Optimizer apply (Task 5):** `SetTargetsButton` maps optimizer `weights` → targets (both apply-to-targets surfaces reuse `useApplyTargets`).
- **Wiring (Task 6):** `PortfolioBuilder` gained Risk + Rebalance full-width sections + "Set as targets" on the optimize result. Optimize method-selector tier gating untouched (QV-056/057).
- **Gates:** backend **661 passed/5 skipped** (ruff/format/mypy-251/lint-imports-3-3/bandit-0/pip-audit-0); frontend **76 vitest passed**, tsc clean, eslint clean, `next build` green. Playwright `portfolio.spec.ts` authored (runs against staging post-merge).
- Reconcile ride-along: QV-079 marked **done** (merged PR #68) in this branch's sprint-status + story file (prior-story reconcile).

### File List

**Backend — Modified**
- `backend/src/quantvista/portfolio/risk.py` — `RiskMetrics.drawdown_series`; `_series_metrics` returns `(scalars, series)`
- `backend/src/quantvista/schemas/risk.py` — `DrawdownPointDTO` + `RiskResponse.drawdown_series`
- `backend/src/quantvista/api/routes_portfolios.py` — map `drawdown_series` in the risk handler
- `backend/tests/test_risk_engine.py` — 3 drawdown-series unit tests + `_dated_returns` helper
- `backend/tests/integration/test_api_risk.py` — `test_risk_includes_drawdown_series`

**Frontend — New**
- `frontend/src/lib/risk.ts` + `risk.test.ts` — pure formatters/mappers
- `frontend/src/features/portfolios/RiskDashboard.tsx` + `.test.tsx`
- `frontend/src/features/portfolios/SectorExposureChart.tsx`
- `frontend/src/features/portfolios/DrawdownChart.tsx`
- `frontend/src/features/portfolios/RebalancePanel.tsx` + `.test.tsx`
- `frontend/src/features/portfolios/SetTargetsButton.tsx` + `.test.tsx`
- `frontend/e2e/portfolio.spec.ts`

**Frontend — Modified**
- `frontend/src/lib/api/queries.ts` — types + `useRisk`/`useRebalance`/`useApplyTargets` + `RiskError`/`RebalanceError`
- `frontend/src/features/portfolios/PortfolioBuilder.tsx` — Risk + Rebalance sections + Set-as-targets
- `frontend/src/lib/api/{openapi.json, schema.d.ts}` — regenerated (adds `/risk`, `/rebalance`, `drawdown_series`)

**Docs**
- `_bmad-output/implementation-artifacts/{7-10-qv-060-…md, sprint-status.yaml}` — this story; QV-079 done reconcile
- `_bmad-output/implementation-artifacts/1-7-qv-079-…md` — Status → done (reconcile)

### Change Log

- **2026-07-26 — QV-060 risk dashboard + rebalancing UI (FE + small BE).** Backend: additive `drawdown_series` on `GET /risk` (already-computed series now exposed; no migration). Frontend: regen typed client; `useRisk`/`useRebalance`/`useApplyTargets` hooks; risk dashboard (metric tiles + sector-exposure bar + real drawdown-over-time area chart + beta coverage); rebalance panel (drift check + buy/sell trades + apply-targets); optimizer "Set as targets" — both apply-to-targets surfaces via one shared hook; wired into the portfolio detail page. Backend 661 passed/5 skipped; frontend 76 vitest + tsc + eslint + build green. Playwright portfolio spec authored (staging post-merge). Also reconciles QV-079 → done (merged PR #68).

---

## Resolved decisions (with {user_name})

1. **Apply-to-targets → BOTH surfaces** (AC 5): optimizer result "Set as targets" **and** rebalance "Apply targets", via a shared `useApplyTargets`.
2. **Drawdown chart → real, folded in** (AC 0/3): expose the already-computed `drawdown_series` on `/risk` (small `[BE]` add) and render a true drawdown-over-time chart. QV-060 is therefore a small **FE+BE** story.

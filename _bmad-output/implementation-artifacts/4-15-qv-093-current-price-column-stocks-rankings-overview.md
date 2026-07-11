---
baseline_commit: 710fbbe04a1ee4e93a0d765838547e0169009a94
---

# Story 4.15: QV-093 — Current Price column (Stocks / Rankings / Overview)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **the latest price shown alongside the score in the Stocks list, Rankings, and Overview**,
so that **I can read a name's price and score together without opening its detail page**.

> Canonical ID **QV-093** · Epic 4 (EPIC-INTEL) · `[BE]` `[FE]` · 2pts · depends: **QV-033 ✅** (stocks/rankings API), **QV-035 ✅** (list/overview FE) · added post-hoc (user request).

## What exists (reuse)

- **`daily_prices`** holds latest close (dev = yfinance, **T-1**). The **stock-detail** query + the **screener** query already LATERAL-join the latest close (`WHERE stock_id = s.id ORDER BY date DESC LIMIT 1`) — the exact pattern to add to the list + rankings reads.
- **`list_stocks`** (`analytics/repositories.py`, `_LIST_STOCKS_SQL`) already sub-selects the latest composite; add the same-shaped latest-`close` sub-select. **`rankings_for`** (`_RANKINGS_SQL`) likewise.
- **Schemas** — `StockListItem` (`schemas/stocks.py`) + `RankingItem` (`schemas/scores.py`); add `close: float | None`.
- **Frontend** — typed client (`gen:api`), `DataTable`, the `stocks`/`rankings` pages + `dashboard.tsx` top-movers. There's an established `₹{close.toFixed(2)}` rendering on the stock-detail page to mirror; `formatScore`/`tabular-nums` conventions.

## Locked decisions

- **Latest close, nullable.** Add `close: float | None` to `StockListItem` + `RankingItem`, sourced from a LATERAL/sub-select of the newest `daily_prices.close` per stock (same as detail/screener). NULL when a stock has no price yet → renders as `—`. **T-1 dev caveat** stands (yfinance close is last completed session); no "live" claim.
- **Three surfaces get a Price column** — Stocks list, Rankings, and the Overview top-movers list. Rendered `₹{close.toFixed(2)}`, right-aligned `tabular-nums`, `—` when null. Not sortable-by-price this story (keep scope tight; sort stays by symbol/composite).
- **No migration, no new endpoint** — additive field on existing reads + existing responses.

## Acceptance Criteria

1. **API.** `GET /api/v1/stocks` items and `GET /api/v1/rankings` items include `close` (latest `daily_prices.close`, nullable). Existing fields unchanged; no new endpoint; no migration.
2. **Queries.** `list_stocks` + `rankings_for` return the latest close via a per-stock newest-row sub-select (matches detail/screener); NULL-safe.
3. **Frontend.** Stocks, Rankings, and Overview top-movers show a **Price** column/value: `₹` + 2dp, right-aligned tabular-nums, `—` when null. Typed client regenerated.
4. **Gates.** Backend: `ruff`/`ruff format`/`mypy --strict`/`lint-imports`/`pytest` green (integration asserts `close` present). Frontend: `eslint`/`tsc`/`vitest` green; `next build` clean.

## Tasks / Subtasks

- [x] **Task 1 — API + queries** (AC: #1, #2)
  - [x] `schemas`: `close: float | None` on `StockListItem` + `RankingItem`. `analytics/repositories.py`: latest-close sub-select added to `_LIST_STOCKS_SQL` + `_RANKINGS_SQL`; `close` mapped in `list_stocks` + `rankings_for`; rankings route adds `"close": r.get("close")` (`.get` survives pre-QV-093 cached rows). Integration tests assert `close` (list → 101.0; rankings → field present).
- [x] **Task 2 — frontend** (AC: #3)
  - [x] Refreshed `openapi.json` + `gen:api`. **Price** column added to `stocks/page.tsx` + `rankings/page.tsx`, and price beside the score in `dashboard.tsx` top-movers; `formatPrice` helper in `lib/score.ts` (`₹` 2dp, `—` when null), right-aligned `tabular-nums`.
- [x] **Task 3 — gates + reconcile** (AC: #4)
  - [x] Backend: ruff/mypy-strict/import-linter clean, `pytest` 355 passed. Frontend: eslint 0, tsc clean, vitest 46. Verified query returns real closes live (360ONE ₹1100.2, ABB ₹6820, FEDERALBNK ₹327.75). Reconcile QV-042 → done (applied on this branch).

## Dev Notes

Mirror the existing latest-close sub-select (`SELECT close FROM daily_prices WHERE stock_id = s.id ORDER BY date DESC LIMIT 1`). Decimal → float via the existing `_f` helper. FE: one `formatPrice(n)` → `n == null ? "—" : "₹" + n.toFixed(2)`, reused across the three surfaces; right-aligned `tabular-nums` like the score cells. **Not this story:** sort-by-price, intraday/live price (T-1 dev), currency/locale beyond ₹, price on the screener table (already has fundamentals; can add later if wanted).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** backend `ruff` + `ruff format` + `mypy --strict` (173 files) + `lint-imports` 3/3 + `pytest`
  **355 passed / 4 skipped** (close assertions added); frontend `eslint` 0 + `tsc` clean + `vitest` 46.
- **Live query check:** `list_stocks`/`rankings_for` return real closes (360ONE ₹1100.2, ABB ₹6820,
  FEDERALBNK ₹327.75, GRASIM ₹3191.9). The *running dev server* showed `null` only because it was serving
  **stale code** (not reloaded) — restarted to pick up the change; rankings also needed a **cache flush**
  (`cached_rankings` held pre-QV-093 rows without `close`; the route's `.get("close")` degrades those to null
  until the cache re-warms on the next `ScoresComputed`).
- **T-1 caveat:** dev close is the last completed session (yfinance); not intraday/live.

### Completion Notes List

- **Latest price now shows next to the score** on Stocks, Rankings, and the Overview top-movers — `close` is an
  additive nullable field on `StockListItem` + `RankingItem`, sourced from the newest `daily_prices.close` per
  stock (same sub-select the detail/screener reads use). **No migration, no new endpoint.**
- **Cache-safe:** the rankings route reads `r.get("close")` so any ranking rows cached before this change render
  as `—` rather than erroring; they self-heal on the next scores recompute / cache-warm.
- **Not this story:** sort-by-price, intraday/live price (T-1 dev), price on the screener table, currency/locale
  beyond ₹.

### File List

**Modified (backend/)**
- `src/quantvista/schemas/stocks.py` + `schemas/scores.py` (`close` field) ·
  `src/quantvista/analytics/repositories.py` (`_LIST_STOCKS_SQL`/`_RANKINGS_SQL` close sub-select + mapping) ·
  `src/quantvista/api/routes_scores.py` (rankings `close`) ·
  `tests/integration/test_api_stocks.py` + `test_api_scores.py` (close assertions)

**Modified (frontend/)**
- `src/lib/score.ts` (`formatPrice`) · `src/app/(app)/stocks/page.tsx` + `rankings/page.tsx` (Price column) ·
  `src/components/dashboard.tsx` (price in top-movers) · `src/lib/api/{openapi.json, schema.d.ts}` (regenerated)

**Modified (repo):** `_bmad-output/.../sprint-status.yaml` (QV-093 status; QV-042 → done reconcile) + epics.

### Change Log

- **2026-07-11 — QV-093 Current Price column (Stocks / Rankings / Overview).** Additive nullable `close` (latest
  `daily_prices` close, T-1 dev) on `/stocks` + `/rankings` responses via a per-stock newest-row sub-select; a
  **Price** column (`₹` 2dp, `—` when null) on the Stocks list, Rankings, and Overview top-movers. No migration,
  no new endpoint. 355 backend tests + 46 frontend green; all gates clean. Reconciles QV-042 → done.

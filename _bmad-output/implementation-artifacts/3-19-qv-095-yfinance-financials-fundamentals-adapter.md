---
baseline_commit: 71c77c0e7a7155d2bbe6f4c3e135e6e0ce07d734
---

# Story 3.19: QV-095 — yfinance-financials fundamentals adapter (dev)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **real fundamental ratios (ROE, ROCE, D/E, margins, growth, PE, PB…) for the Nifty 200 in dev**,
so that **the fundamental/quality factors, the PE/PB/ROE/ROCE/DE screener filters, and the stock-detail metrics stop reading "—"**.

> Canonical ID **QV-095** · Epic 3 (EPIC-DATA) · `[DATA]` · 5pts · depends: **QV-021 ✅** (bitemporal store), **QV-022 ✅** (ingest seam), **QV-092 ✅** (Nifty 200 universe) · added post-hoc (user request).

## Problem (why)

Everything downstream of fundamentals is **already built** — the `fundamentals` table has **22 ratio columns**, the factors (PE/PB/ROE/ROCE/DE, QV-028), scoring, screener filters, and the stock-detail block all consume them. But the dev adapter's `get_fundamentals` returns a **`period_end=None` TTM stub** from yfinance `.info`, which the bitemporal store correctly **rejects** (no filing date) → the table is empty, so composite coverage sits at ~50% (momentum + risk only) and the fundamental filters return nothing. **Verified:** yfinance `income_stmt`/`balance_sheet`/`cashflow` return **dated** statements for NSE stocks (RELIANCE.NS: 2026-03-31…2022-03-31), so computing ratios from them yields dated fundamentals that pass the store and flow straight through.

## What exists (reuse)

- **`fundamentals` table (0005)** — 22 ratio columns + bitemporal (`period_end`, `statement_type`, `reported_at`, `knowledge_from/to`). `record_fundamental_version` (QV-021) accepts any subset of the ratio allowlist. **No migration.**
- **Ingestion seam (QV-022)** — `FundamentalsIngestionService` iterates the universe → `get_fundamentals` → `record_fundamental_version` per filing (skips `period_end=None`), strict per-stock isolation, emits `FundamentalsUpdated`. `ingest_fundamentals` task. **Unchanged** except it now actually lands rows.
- **Adapter (`market_data/adapters/yfinance_dev.py`)** — `YFinanceDevProvider.get_fundamentals` (the stub to rewrite); `_dec`, `_ticker`, provenance helpers. yfinance is the `[dev-data]` extra (lazy import).
- **Downstream (already built):** factors `PEFactor/PBFactor/ROEFactor/ROCEFactor/DebtEquityFactor`; the ScoreEngine re-normalizes category weights over available data (coverage rises automatically); screener DSL fields; stock-detail + screener LATERAL reads of the ratio columns.

## Locked decisions

- **Widen `FundamentalSnapshot` + `_SNAPSHOT_RATIOS`** to the full 22 (table already has the columns → no migration). Add: `roic, revenue, revenue_growth, eps, eps_growth, fcf, fcf_growth, operating_margin, net_margin, current_ratio, quick_ratio, ev_ebitda, peg, price_sales, enterprise_value` (pe/forward_pe/pb/roe/roce/debt_equity already present).
- **Pure ratio module `market_data/ratios.py`** — computes ratios from a normalized statement bundle (income/balance/cashflow line items + shares + price). **Statement-intrinsic** ratios (period-correct, no price): `roe, roce, roic, debt_equity, operating_margin, net_margin, current_ratio, quick_ratio, revenue, eps, fcf` + YoY growth (`revenue_growth, eps_growth, fcf_growth` from the prior period). **Valuation** ratios (price-dependent): `pe, forward_pe, pb, ev_ebitda, price_sales, peg, enterprise_value` — computed **only for the latest period** using the current price + shares (documented as a daily-refreshed snapshot, not a per-period fundamental; the "truly dynamic per-day valuation" is a future refinement). Missing/zero-denominator → `None`. Pure + heavily unit-tested (this is the correctness surface).
- **Adapter rewrite** — `get_fundamentals(symbol)` pulls `income_stmt`/`balance_sheet`/`cashflow` (annual; robust to yfinance's varying line-item names via a lookup with fallbacks; INR/units passthrough), builds a per-period bundle, calls `ratios.compute(...)`, returns a `FundamentalSnapshot` **per period** with `period_end` = the statement date and `statement_type = "annual"`. `reported_at` ≈ `period_end + ~45d` filing lag (Indian norm) so knowledge-time is realistic for the leakage guard. No statements → `[]` (best-effort, per-stock isolation upstream).
- **Dev-grade + license-gated.** yfinance = **non-commercial** (`license_class` stays `non_commercial_dev`); the QV-076 gate (don't serve to paid tiers) applies; the licensed vendor (QV-072) remains the production path. This **upgrades the ceiling** (dev now has fundamentals) without removing it.
- **Backfill run** — `ingest_fundamentals('NSE')` (tolerant, 200 stocks, rate-limit-aware) → then `compute_factors`/`compute_scores` → verify PE/ROE/ROCE + coverage in scores + screener + UI.

## Acceptance Criteria

1. **Ratios module.** `ratios.compute(bundle) -> dict` returns the statement-intrinsic ratios (roe, roce, roic, debt_equity, margins, current/quick, revenue/eps/fcf, growth) + valuation (pe/pb/ev_ebitda/price_sales/peg/ev, latest only); missing inputs / zero denominators → `None`. Pure, unit-tested against a canned statement bundle (incl. a real-shaped case + missing-item + zero-denominator).
2. **DTO + mapping.** `FundamentalSnapshot` + `_SNAPSHOT_RATIOS` carry all 22; `record_fundamental_version` persists them (ratio allowlist already covers them).
3. **Adapter.** `get_fundamentals` returns one dated `FundamentalSnapshot` per annual period (real `period_end`, `reported_at`), computed via `ratios`; robust to missing line items; network-free unit test (stubbed statements).
4. **End-to-end (live dev).** `ingest_fundamentals` lands fundamentals for the Nifty 200; `compute_factors`/`compute_scores` populate ROE/ROCE/DE/PE/PB; **composite coverage rises materially** (~50% → ~90%); `/screener` `pe<=…`/`roe>=…` filters return matches; stock-detail shows real ratios.
4b. **Bitemporal correctness.** Rows carry `period_end` (statement date) + `knowledge_from`; a leakage read as-of a past date does not see a later-`period_end` filing (QV-037 guard remains green).
5. **Gates + boundaries.** `ruff`/`ruff format`/`mypy --strict`/`lint-imports`/`pytest` green (ratios module ≥90%). No migration.
6. **Tests.** Unit: `ratios.compute` (formulas, missing, zero-denom, growth needs 2 periods); adapter parse (stubbed yfinance statements → dated snapshots). Integration (real PG): a fake provider returning a dated multi-period snapshot → `ingest_fundamentals` records versions; `fundamentals_as_of` reads them; factors pick them up.

## Tasks / Subtasks

- [x] **Task 1 — ratios module + DTO widen** (AC: #1, #2)
  - [x] `market_data/ratios.py`: `StatementBundle` + `compute() -> dict[str, Decimal|None]` (all formulas; None-safe). Widen `FundamentalSnapshot` + `_SNAPSHOT_RATIOS`. Unit tests.
- [x] **Task 2 — adapter rewrite** (AC: #3)
  - [x] `yfinance_dev.py`: `get_fundamentals` reads statements (line-item lookup + fallbacks), per-period bundle → `ratios.compute`, dated `FundamentalSnapshot`s (latest carries valuation from current price). Network-free unit test.
- [x] **Task 3 — ingest + verify** (AC: #4, #4b)
  - [x] Run `ingest_fundamentals('NSE')` (tolerant) → `compute_factors`/`compute_scores`. Verify fundamentals rows, coverage lift, screener filters, stock-detail. Confirm QV-037 leakage test still green.
- [x] **Task 4 — tests + gates + reconcile** (AC: #5, #6)
  - [x] Integration `test_fundamentals_ingest` (fake dated provider). Run gates. Reconcile QV-094 → done (already applied on this branch).

## Dev Notes

### Ratio formulas (statement-intrinsic; latest FY)
`roe = net_income / equity` · `roce = ebit / (total_assets − current_liabilities)` · `roic = nopat / invested_capital` (nopat ≈ ebit·(1−tax_rate); invested ≈ debt + equity − cash) · `debt_equity = total_debt / equity` · `operating_margin = operating_income / revenue` · `net_margin = net_income / revenue` · `current_ratio = current_assets / current_liabilities` · `quick_ratio = (current_assets − inventory) / current_liabilities` · `eps = net_income / shares` · `fcf = operating_cash_flow − capex` · growth = `(cur − prior) / |prior|` (needs 2 periods). **Valuation (latest, price P, shares N):** `pe = P / eps` · `pb = P / (equity/N)` · `price_sales = (P·N) / revenue` · `enterprise_value = P·N + total_debt − cash` · `ev_ebitda = ev / ebitda` · `forward_pe = P / forward_eps` (if available) · `peg = pe / (eps_growth·100)`.

### yfinance robustness
Line-item names vary — use a small lookup per metric with fallbacks (e.g. Net Income: `"Net Income"`, `"Net Income Common Stockholders"`). Values are INR absolute (crores scale) — ratios are unit-free, so passthrough is fine; only `eps`/`revenue` absolutes carry units (store as-is). Missing statement / line item → that ratio `None`. 200 stocks × 3 statements is slow + 429-prone → the ingestion service already isolates per stock; run tolerant.

### Not this story
Truly per-day dynamic valuation (recompute pe from each day's price at read time — a factor/read-model change), shareholding/ownership (QV-023), schema widen for extra ratios (ROA, interest coverage, asset turnover, dividend payout — a later increment), quarterly statements, the licensed vendor (QV-072). No migration.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Live pipeline (NIFTY200, real Yahoo): `ingest_fundamentals` → **953 dated fundamentals rows** (200/200 stocks), 250s; `compute_factors` + `compute_scores` succeeded.
- Coverage lift: composite score coverage **avg 49.4% → 97.2%** (max 100%) once fundamental factors (pe/pb/roe 199, debt_equity 195, roce 164 of 200) came online.
- Screener smoke: `pe∈[5,30] & roe≥0.15` → 35 real matches (BPCL pe=5.12/roe=0.26, PFC, RECLTD…). Stock-detail RELIANCE: pe=21.9, pb=1.96, roe=0.089, roce=0.09, d/e=0.44, fundamental_score=31.3, coverage=100%.

### Completion Notes List

- **Statement-intrinsic vs valuation split** kept: intrinsic ratios are period-correct on every dated period; valuation (pe/pb/ps/ev/peg/forward_pe) is added to the **latest period only** from the current price (older periods carry `pe=None` by design). Confirmed in DB: pe non-null=199 (≈latest period per stock) vs roe non-null=783 (all periods).
- **Integration gap found + fixed:** the adapter now emits `statement_type="annual"` (yfinance `.income_stmt` is annual; a single quarter's EPS would make PE ~4× too high), but the factor reader defaulted to `"quarterly"` → factors saw nothing. Made `fundamentals_as_of` / `ScoringContext.fundamentals_as_of` **cadence-agnostic** (`statement_type=None` → latest of any cadence). This fixes coverage without mislabeling data and keeps every existing quarterly-seeded test green; type-specific reads (corrections) still pass an explicit cadence. Added `PRIMARY_STATEMENT_TYPE="annual"` constant for the ingest stamp.
- **Knowledge-time (PIT) timing note:** fundamentals become visible to scoring the run *after* they are ingested (the bitemporal leakage guard, QV-037, correctly hides a filing whose `knowledge_from` is later than the score's as-of day). The nightly `compute_factors`/`compute_scores` after each fundamentals ingest picks them up; the demo above recomputed as-of the ingest day to show the lift immediately. QV-037 leakage test still green.
- No migration: the 22 ratio columns already existed (0005); this is a DTO/adapter/read-default change only.

### File List

- `backend/src/quantvista/market_data/ratios.py` (new) — pure `StatementBundle` + `compute()`
- `backend/src/quantvista/market_data/adapters/yfinance_dev.py` — `get_fundamentals` reads dated statements → per-period snapshots
- `backend/src/quantvista/market_data/models.py` — widened `FundamentalSnapshot` (appended ratio fields, default None)
- `backend/src/quantvista/market_data/services.py` — `_SNAPSHOT_RATIOS` widened; ingest stamps `PRIMARY_STATEMENT_TYPE`
- `backend/src/quantvista/market_data/fundamentals.py` — `PRIMARY_STATEMENT_TYPE`; `fundamentals_as_of` cadence-agnostic (`statement_type=None`)
- `backend/src/quantvista/analytics/context.py` — `ScoringContext.fundamentals_as_of` default `None` (cadence-agnostic)
- `backend/tests/test_ratios.py` (new), `backend/tests/test_fundamentals_adapter.py` (new)
- `backend/tests/test_market_data_provider.py` — replaced `.info`-stub test with empty-without-statements
- `backend/tests/integration/test_fundamentals_ingest.py` — added dated multi-period + widened-ratio test

### Change Log

- QV-095: yfinance-financials fundamentals adapter — dev fundamentals now computed from dated annual financial statements (statement-intrinsic ratios stored bitemporally into the existing 22 columns; valuation ratios from current price on the latest period). Factor/score coverage lifts ~49% → ~97%. Reader made cadence-agnostic. No migration.

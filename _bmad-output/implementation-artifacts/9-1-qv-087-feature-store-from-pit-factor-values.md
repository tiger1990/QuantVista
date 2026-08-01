---
baseline_commit: 23b62422b86314c55dc0ebcbbed1ae93b3643372
---

# Story 9.1: QV-087 — Feature store from PIT factor values

Status: ready-for-dev

**Epic:** EPIC-ML (Epic 9) · **Points:** 5 · **Depends:** QV-029 (factor engine + persisted `factor_values`)

> **The first story of Epic 9, and the one that decides whether the rest is trustworthy.** Every ML claim downstream — walk-forward CV (QV-088), the champion/challenger gate (QV-089), batch serving (QV-090) — rests on features that are point-in-time and identical between training and serving. `factor_values` is already PIT by construction (each row is what was knowable on its date), so the job here is to **build a panel over it without reintroducing look-ahead in the engineering**, and to make train/serve parity structural rather than a promise.

## Story

As an ML engineer, I want training features identical to serving features, so there's no train/serve skew or leakage.

## Acceptance Criteria

1. **A new `quantvista.ml` bounded context** — Epic 9 has five stories; they need a home. `ml` reads `analytics` (factor_values) and `market_data`, so it must sit **above** them in the import-linter DAG. Recommended placement is as a **sibling of `portfolio`** (`quantvista.portfolio | quantvista.ml`) — neither uses the other, and siblings express that honestly. `.importlinter` must be updated in the same change or `lint-imports` fails.
   [Source: `.importlinter` layered contract; `plans/02-architecture.md` §4]

2. **A panel read over `factor_values`** — the existing `factor_values_for(session, stock_ids, as_of)` returns **one date**. Training needs a range. Add a panel read returning `(stock_id, date, factor_key, raw_value, zscore, percentile_sector, percentile_universe)` across `[start, end]`, Polars-shaped. Do **not** widen the single-date function — the scoring path depends on its exact semantics ("scores bind to a single committed snapshot").
   [Source: `analytics/repositories.py:113 factor_values_for`]

3. **100+ engineered features, all strictly backward-looking.** The base is **11 factors × 4 representations = 44 columns** (`raw_value`, `zscore`, `percentile_sector`, `percentile_universe` for `pe, pb, roe, roce, debt_equity, ret_3m, ret_6m, ret_12m, beta, vol_30d, sentiment`). Reach 100+ by **time-series engineering on the z-score panel**: lags (e.g. 21/63 sessions), deltas over those horizons, and rolling mean/std. Every derived column must use `.shift()`/rolling windows that reference **only past rows** — a rolling window that includes the current row is fine, one that centres or looks forward is leakage.
   [Source: `analytics/factors.py ALL_FACTORS`; `05` §5 "100+ engineered features"]

4. **Train/serve parity is structural, not documented.** One function produces the feature row for a given `(stock, date)`, and both the training panel and any future serving call go through it. A test must assert that the panel's row for a date equals the single-date serve call for that same date — if they can diverge, the epic's central claim is already false.
   [Source: `05` §5 "reusing `factor_values` guarantees train/serve consistency"]

5. **A documented feature catalog** — `docs/feature-catalog.md` listing every feature with its family, source factor, transform and window. Follow the QV-011 precedent: **the catalog is generated from, or drift-tested against, the code**, so it cannot rot. A test must fail when a feature exists without a catalog entry.
   [Source: sprint-12 AC "documented feature catalog"; `docs/terminology-guide.md` precedent]

6. **A leakage guard in the spirit of QV-066.** At least one test constructs a panel where a future value would change a feature if leaked, and asserts it does not. This epic's whole value proposition is "honest performance"; a feature store without a leakage test is an unverified claim.
   [Source: `tests/integration/test_bias_regression.py`; QV-066]

7. **Gates green** — backend ruff/format, mypy, `lint-imports` (with the new contract), full pytest.

## Tasks / Subtasks

- [ ] **Task 1 — context + contract (AC: 1)**
  - [ ] `src/quantvista/ml/` package; add to `.importlinter` layers; confirm `lint-imports` passes *and* that a deliberate `ml → portfolio` import fails it.
- [ ] **Task 2 — panel read (AC: 2)**
  - [ ] Range read in `analytics/repositories.py`; leave `factor_values_for` untouched.
- [ ] **Task 3 — feature engineering (AC: 3)**
  - [ ] Polars pipeline: base 44 + lags/deltas/rolling → 100+; assert the count in a test so "100+" is enforced, not aspirational.
- [ ] **Task 4 — parity seam (AC: 4)**
  - [ ] Single function used by both paths + the equality test.
- [ ] **Task 5 — catalog (AC: 5)**
  - [ ] `docs/feature-catalog.md` + drift test.
- [ ] **Task 6 — leakage guard + gates (AC: 6, 7)**

## Dev Notes

### What already exists (read before writing)

- **`analytics/factors.py`** — `ALL_FACTORS` is 11 concrete `Factor`s. `sentiment` yields values only where news exists, so **expect nulls**; the pipeline must not silently drop a stock because one factor is missing (that would bias the training set toward well-covered names).
- **`analytics/repositories.py`** — `upsert_factor_values` (write) and `factor_values_for` (single-date read). The panel read is new; mirror the SQL style (module-level `text()` constant).
- **`analytics/normalizer.py`** — z-scores are already sector-relative and winsorized, so **do not re-normalise**. Re-standardising an already-standardised column is a common and silent modelling error.
- **`market_data/trading_calendar.py`** — `sessions_in_range` is the canonical session list. Use it for the panel's date spine rather than `SELECT DISTINCT date`, and note the reason in the code: the dev feed returns bars on some exchange holidays, which is exactly what broke the QV-105 coverage metric.

### Point-in-time: what is already safe, and what is not

**Safe by construction:** a `factor_values` row for date `D` was computed from data knowable at `D` (QV-029 + the QV-063/064 PIT seams). Reading rows with `date <= T` cannot leak.

**Not safe automatically:** the engineering. A rolling mean over a window that includes future rows, a `fill_null(strategy="backward")`, or a cross-sectional statistic computed over the whole panel rather than per-date all leak. Prefer `over("stock_id")` with explicit ordering, and never `backward`/`mean` imputation across time.

### Data reality on this box (affects test design, not correctness)

`factor_values` currently covers **255 sessions** (2025-06-02 → 2026-07-24); the earliest ~30 sessions have none, because factors need indicator lookback. Integration tests should seed their own small panel rather than assume ambient coverage — the shared dev database has bitten this project repeatedly (see the QV-105 fixture that deleted rows but left `jobs_runs`, and the notification test that asserted a global count).

### Scope boundary

- **Features only.** Labels, CV splits, embargo and model training are **QV-088**. Do not add a target column here beyond what a feature needs.
- **No training libraries.** They arrive with QV-088 — but the feasibility question is now **answered** (checked 2026-08-01, so QV-088 need not be scoped blind):
  - **LightGBM works on this box** via a source build with OpenMP disabled: `pip install --no-binary lightgbm --config-settings=cmake.define.USE_OPENMP=OFF lightgbm`. Verified end-to-end — 200 trees on 3000×40 in 0.96s single-threaded, and **`LGBMRanker` (learning-to-rank) runs**, which is what QV-088 specifies. `scikit-learn 1.9.0` installs normally.
  - **The stock wheels do not import**: both LightGBM and XGBoost fail on a missing `libomp.dylib`, and Homebrew has no bottle for it on macOS 12. **XGBoost stays blocked** locally.
  - `05` §5 names LightGBM for the risk model and treats XGBoost/CatBoost as alternatives, so **standardising Epic 9 on LightGBM costs nothing against the spec**. CI is Linux, where the stock wheels install normally.
- **No serving path.** QV-090 writes ML scores; this story only guarantees the seam exists.

### Previous-story / epic intelligence

Epic 9 has no prior stories. The most relevant recent work is **QV-105** (merged PR #82/#83): it added range backfills for derived data and a coverage gauge, and its lesson applies directly here — *the derived data this story reads is only as deep as the backfill made it*. If a training panel looks thin, check `data_coverage_gap_sessions` before suspecting the pipeline.

Two habits from the last five PRs that should carry into this one:
1. **Negative-control every guard.** Each of the recent guards (routing, partitions, terminology, coverage) was verified by deliberately breaking it. A leakage test that has never failed is not evidence.
2. **Prefer a structural check over a documented promise.** Parity and the catalog should both be test-enforced, following `test_methodology_constants.py` and `test_terminology_guard.py`.

### Git intelligence (recent)

`23b6242 coverage-basis fix #83` (this baseline) · `ba13d52 QV-105 #82` · `118422a QV-011 #81`. Polars **1.42.1** is installed and is the project's vectorisation tool (`normalizer.py`, `indicators.py` are the precedents for Polars-heavy code).

### Project context reference

`_bmad-output/project-context.md` · `plans/05-domain-and-quant.md` §5 (ML architecture) · `plans/02-architecture.md` §4 (context DAG) · the backend-layout memory (`backend/src/quantvista/<context>/`).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

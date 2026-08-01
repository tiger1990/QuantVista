---
baseline_commit: 23b62422b86314c55dc0ebcbbed1ae93b3643372
---

# Story 9.1: QV-087 — Feature store from PIT factor values

Status: review

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
- **No training libraries.** They arrive with QV-088 — and the feasibility question is **settled** (2026-08-01), so QV-088 need not be scoped blind or hedged:
  - **Both LightGBM 4.7.0 and XGBoost 3.3.0 work on this box with stock wheels**, after `brew install libomp` (22.1.8). The wheels always matched the platform; macOS simply does not ship LLVM's OpenMP runtime, so both failed at import until libomp was installed.
  - Verified: `LGBMRegressor` fits 200 trees on 3000×40 in **0.41s**, `XGBRegressor` in **1.64s**, and **both `LGBMRanker` and `XGBRanker` run** — learning-to-rank is what QV-088 specifies.
  - **Do not defer any Epic 9 story as "ML deps unavailable"** — unlike torch (no compatible wheel at all), this was a packaging gap that is now closed. CI is Linux, where the stock wheels install normally, so no CI change is needed.
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

## Tasks — completed

- [x] **Task 1** — `quantvista.ml` context created; `.importlinter` layer added as a sibling of `portfolio`; contracts 3/3 kept.
- [x] **Task 2** — `factor_values_panel` range read added; `factor_values_for` untouched (pinned by a test).
- [x] **Task 3** — Polars pipeline producing **132 features** from 11 factors; the count is asserted.
- [x] **Task 4** — `serve_features` is a thin alias over `build_features`; parity asserted and negative-controlled.
- [x] **Task 5** — `docs/feature-catalog.md` generated by `scripts/render_feature_catalog.py`; drift-tested.
- [x] **Task 6** — leakage guard + 19 tests; full gates green.

## Dev Agent Record

### Agent Model Used

claude-opus-5

### Debug Log

- **132 features from 11 factors**, comfortably past the 100+ AC: 44 base (11 × 4 stored representations) + 88 derived (lag/delta/rolling-mean/rolling-std at 21 and 63 sessions). Derived families use **`zscore` only** — it is already sector-relative and winsorized (QV-029), so a change in it means a change in *standing*; differencing a raw P/E across time would conflate level, scale and sector drift.
- **Both guards negative-controlled**, not merely written:
  - centring the rolling window (`center=True`) → the leakage test fails with *"a future value changed a past feature"*;
  - giving serving its own implementation (dropping trailing history) → the parity test fails with *"serving diverged from training"*.
- **The integration test caught a real bug the unit tests could not.** `stock_id` arrives from the repository as a `UUID` object, while the unit tests passed strings; Polars could not hold it in a typed column. Coercing to text inside `_pivot_long_panel` keeps both callers on one schema — otherwise the frame's dtype would depend on who called it.
- **A pre-existing test of mine turned out to be ambient-dependent.** `test_coverage_gap.py` (QV-105) seeded "the last 10 days" and assumed the dev database lacked recent indicator coverage. A pipeline resync from another session filled prices *and* indicators through 2026-07-31, so the gap legitimately became 0 and two assertions failed. Re-anchored to a fixed window of real trading sessions in untouched history (March 2024), so the test now measures the code rather than the database's mood.
- **One unexplained failure, reported rather than buried.** `test_macro_sync::test_sync_stores_the_canonical_key` failed once in a full run, passes in isolation, and did **not** recur across two consecutive full runs. The dev database has concurrent writers — `jobs_runs` shows 49 `run_backtest` executions today plus notification and news jobs — which is the likely cause. Not reproduced, so not claimed as fixed. CI is isolated.

### Completion Notes List

- **Decisions taken with the user:** a dedicated `quantvista.ml` context (rather than growing `analytics`), and an **in-memory Polars frame** as the only output — persistence waits for QV-088 to reveal the trainer's access pattern, instead of committing to a 100+-column schema on speculation.
- **Nulls are preserved deliberately.** A stock with no sentiment coverage must not look like a stock with neutral sentiment; a test asserts absent factors stay null rather than being zero-filled, because imputing here would bias the training set toward well-covered names.
- **Train/serve parity is structural.** `serve_features` is an alias on purpose — if serving had its own implementation, `05` §5's central claim would rest on discipline rather than construction.
- **The catalog is generated.** Following QV-011/QV-070: a hand-maintained feature list is wrong within two stories, and here it is the artifact a reviewer trusts when judging whether a model's inputs are legitimate.

### File List

- `backend/src/quantvista/ml/__init__.py`, `features.py`, `catalog.py` (new — the context)
- `backend/src/quantvista/analytics/repositories.py` (modified — `factor_values_panel`)
- `backend/scripts/render_feature_catalog.py` (new)
- `docs/feature-catalog.md` (new — generated)
- `.importlinter` (modified — `quantvista.portfolio | quantvista.ml` layer)
- `backend/tests/test_ml_features.py`, `test_feature_catalog.py`, `integration/test_factor_panel.py` (new — 19 tests)
- `backend/tests/integration/test_coverage_gap.py` (modified — removed the ambient-data dependency)

### Change Log

- 2026-08-01 — QV-087: PIT feature store over `factor_values`. New `quantvista.ml` context, panel read, 132 backward-only engineered features, structural train/serve parity, generated feature catalog, and a negative-controlled leakage guard. Gates: backend 852 passed/5 skipped, ruff/mypy/lint-imports clean.

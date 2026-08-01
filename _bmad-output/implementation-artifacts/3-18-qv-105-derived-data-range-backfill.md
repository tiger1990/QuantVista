---
baseline_commit: 118422aefe3727266fbdf129e4b2ae3b5629ba75
---

# Story 3.18: QV-105 — Derived-data range backfill (indicators, factors, scores)

Status: review

**Epic:** EPIC-DATA (Epic 3) · **Points:** 3 · **Depends:** QV-016 (price range backfill), QV-025 (compute_indicators), QV-029 (scoring)

> **The gap that made a working feature look broken.** A backtest over a year of data returned `0.00%` on every strategy metric while the benchmark looked healthy — no error anywhere. The cause was not the engine: prices had a range backfill since QV-016, but the *derived* steps ran for a **single date**. A database could hold a year of prices behind one day of indicators, and since the engine ranks off `technical_indicators` at every rebalance date, every rebalance selected zero names.

## Story

As an operator, I want indicators/factors/scores backfilled across a date range, so a new environment produces meaningful backtests instead of silently zeroed ones.

## The defect, precisely

`scripts/dev_backfill.py` did this:

```python
backfill_daily_prices(market, start=start, end=target)   # a RANGE
compute_indicators(market, tiso)                          # ONE date
compute_factors(market, tiso)                             # ONE date
compute_scores(market, tiso)                              # ONE date
```

Observed on the dev database: **286 sessions of prices, 7 days of indicators.** A 2025-07→2026-07 backtest produced 13 rebalance dates, none of which had indicator coverage, so `ranked_universe` returned `[]` at every one — 0% exposure, 0% return, 0 Sharpe, while `benchmark_return` showed 2.75% because the benchmark is pure price maths needing no indicators.

## Acceptance Criteria

1. **`backfill_indicators(market, start, end)`** computes indicators for every trading session in the window, mirroring `backfill_daily_prices`. Idempotent per date.
2. **`backfill_factors_and_scores(market, start, end)`** does the same for the stored factor/score snapshots, running factors→scores **paired per session** (scores blend the persisted snapshot, so ordering matters).
3. **`dev_backfill.py` derives across the whole window by default**, with `--scores-last-day-only` for the fast path when only `/rankings` is needed. Indicators are *always* full-window, because that is what backtests need.
4. **A repair path exists.** The QV-015 ledger skips any date recorded as succeeded, so a date whose first run wrote partial data stays partial forever. `force=True` re-runs regardless, recording each repair as its own ledger entry.
5. **Gates green.**

## Dev Agent Record

### Agent Model Used

claude-opus-5

### Debug Log

- **The ledger's skip is the subtle half of this story.** The first test run surfaced `job_skipped run_key=ind:QV105:2026-03-06` — `run_job` treats a previously-succeeded key as done. For a *fill* that is correct and makes an interrupted backfill cheap to resume. For a *repair* it is wrong: the dev database contained days with 4, 12 and 102 stocks (partial runs from when fewer names were priced), and no ordinary re-run would ever fix them. Hence `force=True`, which is pinned by two tests — one asserting the skip happens without it, one asserting the repair happens with it.
- **My own test isolation was the actual cause of the first failure.** The fixture deleted `technical_indicators` but left `jobs_runs`, so the next test's backfill was skipped and wrote nothing — a failure with nothing to do with the code under test. Fixed by deleting the ledger rows in teardown; verified by running the suite twice consecutively with **0 leftover ledger rows**.
- **Verified the fix is real, not just green:** the suite passes back-to-back, and the window deliberately spans several sessions with an assertion (`len(expected) > 1`) so a one-session window could never make it vacuous.

### Completion Notes List

- **Indicators are the critical path, factors/scores are not.** The backtest engine recomputes scores point-in-time from `technical_indicators` via `compute_universe`; the stored `factor_values`/`scores` feed rankings and score history. That is why indicators are always backfilled in full while scores can be limited to the last day — documented in both the script's flag help and the function docstring so the distinction is not folklore.
- **Scope kept to the backfill.** A coverage *metric* (alerting when derived data lags prices) would be the production-grade guard and is a natural QV-020 follow-up; it is not in this story.
- **Dev-only script, real functions.** The backfill functions live in `jobs/` beside `backfill_daily_prices` and are usable from a worker or shell; `dev_backfill.py` stays the dev convenience wrapper it always was.

### File List

- `backend/src/quantvista/jobs/compute.py` (modified — `backfill_indicators` + `force` repair path)
- `backend/src/quantvista/jobs/scoring.py` (modified — `backfill_factors_and_scores`)
- `backend/scripts/dev_backfill.py` (modified — derives across the window; `--scores-last-day-only`)
- `backend/tests/integration/test_derived_backfill.py` (new — 5 tests incl. skip/repair semantics)

### Change Log

- 2026-08-01 — QV-105: range backfill for derived data. Closes the silent all-zero-backtest trap where a database held a range of prices behind a single date of indicators. Gates: backend 816 passed/5 skipped, ruff/mypy/lint-imports clean.

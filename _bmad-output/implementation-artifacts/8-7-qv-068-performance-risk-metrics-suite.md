---
baseline_commit: 4cc77aeb8d5511ddf3433a01794c018bfe712df3
---

# Story 8.7: QV-068 — Performance & risk metrics suite

Status: done

**Epic:** EPIC-BT (Epic 8) · **Points:** 5 · **Depends:** QV-065 (`BacktestEngine` equity curve + benchmark)

> **The standard yardsticks for judging a strategy.** QV-065 shipped a *core* metric set inline; this story is the full **performance & risk suite** (`05` §4.6): CAGR, annualized vol, Sharpe, **Sortino**, max drawdown, **hit rate**, turnover, **exposure-over-time**, and a proper **benchmark comparison** (tracking error, information ratio, beta). It **extracts** the metrics math out of the engine into a dedicated, exhaustively unit-tested module (pure numpy — exact expected values, no DB), and enriches what the engine already computes. **No new deps, no API/schema change** — the metrics flow through the existing `backtests.metrics` JSONB (Decimal-as-string).

## Story

As a user, I want standard backtest metrics, so I can judge a strategy.

## Acceptance Criteria

1. **Dedicated metrics module** — a new `analytics/backtest_metrics.py::compute_metrics(...)` (pure function of the equity curve, period returns, turnovers, exposures, and the benchmark curve/returns) returns the full metric dict. The `05` §4.6 set: `total_return`, `cagr`, `ann_vol`, `sharpe`, **`sortino`**, `max_drawdown`, **`hit_rate`**, `avg_turnover`, **`avg_exposure`**, `n_rebalances`, `benchmark_return`, `excess_return`, **`tracking_error`**, **`information_ratio`**, **`beta`**, **`exposure_series`**. Every scalar is a **Decimal serialised as a string** (never float); `n_rebalances` is an int; `exposure_series` is a compact per-rebalance `[{as_of, exposure}]`.
   [Source: `05` §4.6; QV-065 `_metrics` (the 9 it already computes)]

2. **The new metrics, defined precisely** —
   - **Sortino** = `mean(r) / downside_deviation × √252`, `downside_deviation = √(mean(min(r,0)²))` (target 0); 0 when no downside.
   - **hit_rate** = fraction of *non-flat* periods with a positive return = `count(r>0) / count(r≠0)`; 0 when all flat.
   - **avg_exposure** = mean invested fraction (`Σ held weights` per period, 0..1); `exposure_series` samples the invested fraction at each rebalance date.
   - **tracking_error** = `std(r_strat − r_bench) × √252`; **information_ratio** = `mean(r_strat − r_bench) / std(r_strat − r_bench) × √252` (0 when TE=0); **beta** = `cov(r_strat, r_bench) / var(r_bench)` (0 when the benchmark is flat).
   [Source: standard quant definitions; `05` §4.6]

3. **Engine wiring — capture what the suite needs** — `BacktestEngine._simulate` additionally tracks the **invested fraction per period** (`Σ held weights`) and `run` captures the **benchmark's period returns** (today discarded as `_`); both feed `compute_metrics`. The rebalance loop, frictions, forced-exit, determinism, and Decimal discipline are **unchanged** — only the metric computation is enriched/moved.
   [Source: QV-065 `_simulate`/`run`; determinism is cardinal]

4. **Deterministic + reproducible** — `compute_metrics` is a pure function of its inputs → identical output on re-run (QV-069 formalises the end-to-end guarantee). `model_version`/`weights_version` continue to be stamped by the engine.
   [Source: QV-065; `03` §9 reproducibility]

5. **Exhaustive unit tests (exact values)** — a new pure-Python `tests/test_backtest_metrics.py` feeds **hand-computed** curves/returns and asserts each metric to the expected value (e.g. a monotonic-up curve → known CAGR/Sharpe/0 drawdown; a curve with a known trough → exact max_drawdown; a returns series with k positives → exact hit_rate; a strategy==benchmark case → beta 1 / TE 0 / IR 0; a downside-only case → Sortino). Update `test_backtest_engine.py` to assert the full key set is present + typed. Existing bias/integration tests keep passing (the metrics dict only grows).
   [Source: testing rules; QV-065 unit-test precedent]

6. **No new deps / API / schema; gates green** — numpy only (already a dep); `backtests.metrics` is `jsonb`/`dict[str, Any]` so the richer dict flows through with **no migration or API change**. Full-tree gates green (ruff, ruff format, **bare `mypy`**, lint-imports **3/3**, bandit, pip-audit); coverage ≥80% on the new module (aim 100% — it's pure math).
   [Source: `analytics/backtests.py` schema (JSONB); QV-062 `BacktestResponse.metrics: dict[str, Any]`]

---

## Dev Notes

### Placement & DAG

- **`analytics/backtest_metrics.py`** (NEW) — `compute_metrics(...)` + `empty_metrics()` (moved from `analytics/backtest.py`) + the `_s` Decimal-serialiser (moved/shared). Pure functions, numpy only. `analytics` self-contained; no new imports, no DAG change (confirm `lint-imports` 3/3).
- **`analytics/backtest.py`** (UPDATE) — `_simulate` returns `(curve, period_returns, turnovers, exposures)`; `run` captures the benchmark's period returns (`bench_curve, bench_returns, _ = self._simulate(...)`) and calls `compute_metrics(...)`. **Delete** the inline `_metrics`/`_empty_metrics`/`_s` (now in the new module) and import them. Keep `BacktestResult`, the loop, and every existing metric key/value identical — this is an *additive* refactor.
- Python 3.13, mypy strict — **run bare `mypy`**. Money/ratios cross into float only inside numpy, serialise back to `str` via `_s`.

### Reuse / do NOT break

- **QV-065 already computes 9 of these** (`total_return`, `cagr`, `ann_vol`, `sharpe`, `max_drawdown`, `avg_turnover`, `n_rebalances`, `benchmark_return`, `excess_return`) — move that math verbatim into `compute_metrics` and *add* the rest. The existing values must not change (the bias/engine/api tests assert some of them).
- **`_simulate` already has `held`** each period — exposure is `sum(held.values())` (cash = the unallocated remainder, so exposure ≤ 1.0; a mid-hold delisting drops it). Append per session, aligned to `sessions`.
- **Benchmark period returns** already exist inside the benchmark `_simulate` call — QV-065 just throws them away (`bench_curve, _, _`). Capture them for TE/IR/beta.
- **Guards** (match QV-065's style): `std==0 → sharpe/sortino/IR = 0`; `var(bench)==0 → beta = 0`; `size < 2 → vol/ratios = 0`; empty range → `empty_metrics()` (now with the new keys, all zero / empty series).

### exposure_series shape + scope

- Store `exposure_series` as `[{"as_of": "YYYY-MM-DD", "exposure": "0.9500"}, …]` at **rebalance dates** (compact: `n_rebalances` points). `avg_exposure` is the scalar mean over all periods.
- **Full daily exposure/equity curves → the result artifact** (QV-067's object store, via `result_ref`) is deferred — QV-067 shipped the store but not the result-artifact write (see `deferred-work.md`). QV-068 puts the compact series + scalars in `metrics`; note the daily series as artifact-bound.

### Scope boundary

- **Metrics only.** Do not touch the rebalance loop, universe/ranking/returns seams, or the object store. The **reproducibility guarantee** (QV-069) and the **frontend that renders these** (QV-071, which depends on QV-068) are separate.
- No new metric the AC doesn't list (no Calmar/Omega/etc. — YAGNI); the AC set + the standard benchmark-comparison trio (TE/IR/beta) is the deliverable.

### Previous-story / epic intelligence

- **QV-065 (PR #74)** put `_metrics`/`_empty_metrics`/`_s` inline in `analytics/backtest.py` and returns the 9-metric core; `_simulate` returns `(curve, period_returns, turnovers)`. QV-068 is the natural extraction + enrichment. Determinism + Decimal-as-string are cardinal; the engine floats internally then serialises.
- **QV-066** proved the engine is bias-free; those guards assert on `metrics` equality/inequality — a growing dict is fine (they compare specific keys / whole-dict within a fixed scenario, not against a golden count).
- `tests/test_backtest_engine.py` has `_METRIC_KEYS` (the 9) + a `FakeData` seam — extend `_METRIC_KEYS` to the full set and reuse `FakeData` for an engine-level "all keys present + typed" test; the deep exact-value tests live in the new pure-math file.

### Git intelligence (recent)

`4cc77ae QV-067 #76` · `8c4afbf QV-066 #75` · `5a12fdf QV-065 #74`. `analytics/backtest.py` `_metrics` is the code being extracted; `tests/test_backtest_engine.py` is the closest template for the engine-level assertion; a fresh pure-math test file is new but simple (numpy + Decimal, no fixtures).

### Project context reference

`_bmad-output/project-context.md` — `backend/src/quantvista/<context>/`; money as `Decimal` via `str`; determinism is cardinal for Epic 8. `05` §4.6 metric list.

## Tasks / Subtasks

### Task 1: Metrics module (AC-1, AC-2)
- [x] `analytics/backtest_metrics.py`: `compute_metrics(*, sessions, curve, period_returns, turnovers, exposures, bench_curve, bench_returns, rebalance_dates, n_rebalances) -> dict[str, Any]` + `empty_metrics()` + `_s`. Moved QV-065's 9 verbatim; added sortino, hit_rate, avg_exposure, exposure_series, tracking_error, information_ratio, beta with the precise definitions + guards.

### Task 2: Engine wiring (AC-3, AC-4)
- [x] `_simulate` now returns `exposures` (`Σ held weights` per session); `run` captures `bench_returns` and calls `compute_metrics`. Deleted the inline `_metrics`/`_empty_metrics`/`_s` (+ numpy import), imported from the new module. Loop/frictions/forced-exit unchanged; versions stamped in both paths via `_stamp`.

### Task 3: Unit tests (AC-5)
- [x] `tests/test_backtest_metrics.py` (11 exact-value tests): total_return/max_drawdown, monotonic → 0 DD + positive Sharpe + 0 Sortino, hit_rate count, Sortino downside-only, strat==bench → beta 1/TE 0/IR 0, beta 2 on 2× returns, flat-bench → beta 0, avg_exposure + exposure_series, avg_turnover, empty_metrics.
- [x] Extended `tests/test_backtest_engine.py` `_METRIC_KEYS` to the full 16 + assert present/typed; bias/api/engine-run suites (21 tests) still green.

### Task 4: Gates (AC-6)
- [x] Full-tree gates green (ruff, format, mypy 276, lint-imports 3/3, bandit, pip-audit); `backtest_metrics.py` 100% / `backtest.py` 99%. Story → review; sprint-status → review; Dev Agent Record filled.

## Dev Agent Record

### Debug Log

- RED: wrote the exact-value tests first against the intended `compute_metrics`/`empty_metrics` API → `ModuleNotFoundError` (module missing), confirming the tests drive the code.
- **Additive refactor:** moved QV-065's 9-metric math verbatim into `compute_metrics`, added the 6 new metrics + `exposure_series`; the existing values are unchanged, so the bias guards (which compare metrics dicts) and the api lifecycle assertion pass untouched.
- Serialisation: `_s(1.0)` → `"1.0"` (not `"1"`) — fixed two `exposure_series` string assertions to match. Values compared via `Decimal(...)` are scale-insensitive, so the exact-value asserts hold.
- mypy: my test helper returned `dict[str, object]` → `Decimal(object)` errors; annotated it `dict[str, Any]` to match `compute_metrics`. A few docstring E501s (the `Σ` glyph counts >1) → reworded.
- Coverage: `backtest_metrics.py` 100%; `backtest.py` 99% (the one uncovered line is the pre-existing `_equal_weight` empty guard, unrelated to this story).

### Completion Notes List

- **Full `05` §4.6 suite** now computed by a dedicated, pure-numpy `analytics/backtest_metrics.py`: `total_return`, `cagr`, `ann_vol`, `sharpe`, **`sortino`**, `max_drawdown`, **`hit_rate`**, `avg_turnover`, **`avg_exposure`**, `n_rebalances`, `benchmark_return`, `excess_return`, **`tracking_error`**, **`information_ratio`**, **`beta`**, **`exposure_series`** — all Decimal-as-string (n_rebalances int; exposure_series a compact per-rebalance list).
- **Engine untouched where it matters:** the rebalance loop, frictions, forced-exit, determinism, and every prior metric *value* are identical; the only engine change is tracking exposure-per-period + capturing the benchmark's period returns (previously discarded) to feed the suite.
- **No new deps / API / schema:** numpy only; `backtests.metrics` is `jsonb`/`dict[str, Any]` so the richer dict flows through. Unblocks the QV-071 frontend (depends on QV-068).
- **Honest scope:** the compact per-rebalance `exposure_series` is in `metrics`; the full daily exposure/equity curves are artifact-bound (QV-067 object store; write-path deferred) — noted, not faked.
- Full suite **749 passed / 5 skipped**; all gates green.

### File List

- `backend/src/quantvista/analytics/backtest_metrics.py` (new — the pure-math suite)
- `backend/src/quantvista/analytics/backtest.py` (modified — `_simulate` tracks exposures, `run` captures bench returns + delegates to `compute_metrics`; inline `_metrics`/`_empty_metrics`/`_s`/numpy removed; `_stamp` helper)
- `backend/tests/test_backtest_metrics.py` (new — 11 exact-value unit tests)
- `backend/tests/test_backtest_engine.py` (modified — `_METRIC_KEYS` → full 16 + typed assertion)

### Change Log

- 2026-07-28 — QV-068 performance & risk metrics suite: extracted the metrics math into `analytics/backtest_metrics.py` and added Sortino, hit rate, exposure-over-time (avg + per-rebalance series), and benchmark comparison (tracking error, information ratio, beta). Pure numpy, no new deps/API/schema; existing metric values unchanged. 11 exact-value unit tests; metrics module 100% covered; gates green.

---
baseline_commit: fc0ff2ca47627438beecaaf53e37d2c03dfba11f
---

# Story 8.4: QV-065 — Backtest engine core (rebalance loop + frictions)

Status: done

**Epic:** EPIC-BT (Epic 8) · **Points:** 8 · **Depends:** QV-063 (`BacktestDataAccess` PIT seam), QV-064 (survivorship-free `universe_as_of` + forced-exit `last_price_as_of`), QV-053 (constraints concept — see DAG note; **not** a code import)

> **The engine that makes a backtest real.** QV-062 shipped the async lifecycle with a placeholder `BacktestEngine.run` that returns empty metrics. This story replaces that body with the **deterministic factor-strategy rebalance loop**: at each rebalance date `D` it reads the survivorship-free universe, ranks it PIT, equal-weights the top-`N`, holds to the next rebalance on adjusted returns, models **transaction costs + slippage + turnover**, force-exits delisted names at last valid price, and produces a core metrics set vs an internal benchmark. Everything is read through the QV-063/064 seam — so the two cardinal sins (look-ahead, survivorship) are structurally impossible. It keeps `BacktestResult`'s shape (metrics + `result_ref`); the **full** metrics suite is QV-068, Parquet artifact offload is QV-067, and the permanent bias-regression CI guards are QV-066.

## Story

As a quant, I want a realistic rebalance simulation, so results reflect tradeable reality.

## Acceptance Criteria

1. **Deterministic factor-strategy rebalance loop** — `BacktestEngine` (in `analytics/backtest.py`) takes a `BacktestDataAccess` and runs `spec` into a `BacktestResult`. Build the rebalance schedule from `market_data.trading_calendar.sessions_in_range(spec.start, spec.end)` bucketed by `spec.rules.rebalance` (weekly/monthly/quarterly → first session of each bucket). At each rebalance `D`: `universe = data.universe_as_of(D)` → `ranked = data.ranked_universe(D, universe, rank_by=spec.rules.rank_by, top_n=spec.rules.top_n)` → **equal-weight** `1/len(ranked)`. Hold to the next rebalance; the daily portfolio return is the weighted sum of adjusted-close returns. **Pure function of PIT data → identical metrics on re-run** (deterministic; no stochastic step to seed, but any tie-break is stable via QV-063).
   [Source: `05` §4; sprint-08 QV-065 AC; QV-063 `ranked_universe`/`returns_as_of`, QV-064 `universe_as_of`]

2. **No look-ahead, no survivorship — for free** — every read is through `BacktestDataAccess` bounded by `D`; the engine **never** queries a table directly and has **no** "latest"/unbounded read. Universe is `universe_as_of` (survivorship-free, incl. later-delisted names), scores are PIT (`ScoringContext`), returns are `date <= D`. This is the structural guarantee — QV-066 will add the permanent counterfactual CI guards; QV-065's own test proves the seam is the only data path.
   [Source: `05` §4.1/§4.2 (the two cardinal sins); QV-063 firewall; QV-064 survivorship-free universe]

3. **Realistic frictions** — at each rebalance, **turnover** = ½·Σ|wₙₑw − wₒₗd| (names not held before have wₒₗd=0); **cost** = turnover · (`spec.costs_bps` + `SLIPPAGE_BPS`)/10 000 is deducted from the equity curve at that rebalance. `SLIPPAGE_BPS` is a documented module constant (a fixed assumption; `spec` carries only `costs_bps`). A run with `costs_bps>0` yields a **strictly lower** total return than the same spec with `costs_bps=0` whenever turnover>0. Average turnover is reported.
   [Source: `05` §4.3 "Transaction costs (bps), slippage, turnover modeled and reported"]

4. **Corporate-action-adjusted returns + delisting forced exit** — returns are computed from `adj_close` (via the QV-063 `returns_as_of` panel), never raw close. A held name that leaves the universe because it delisted (absent from the next `universe_as_of`, or with no bar on a period) is **force-exited at its last valid price** via `data.last_price_as_of` (QV-064); its weight is realised to cash at that price, not dropped silently or marked to zero.
   [Source: `05` §4.2/§4.4; QV-064 `last_price_as_of`; `daily_prices.adj_close`]

5. **Benchmark + core metrics** — benchmark is an **equal-weight buy-and-hold of `universe_as_of`** at `spec.start` (an internal PIT proxy for the Nifty 200 TRI — real TRI licensing is deferred, see market-data strategy), computed on the same `adj_close` discipline. Compute a **core** metric set (the full suite is QV-068): `total_return`, `cagr`, `ann_vol`, `sharpe` (rf=0), `max_drawdown`, `avg_turnover`, `n_rebalances`, `benchmark_return`, `excess_return`. All money/ratio values are **Decimal serialised as strings** (never float) in the persisted `metrics` JSONB. Persist `model_version` (= `analytics.scoring.MODEL_VERSION`) and `weights_version` (= `"equal-weight-v1"`) on the row for reproducibility (QV-069).
   [Source: `05` §4.5/§4.6/§4.7; `analytics.scoring.MODEL_VERSION`; project rule: Decimal-as-string]

6. **Runs on the `user` queue; lifecycle intact** — route `quantvista.run_backtest` to the **`user`** queue (`celery_app.task_routes`) so a long backtest can't starve ingestion/compute. The job keeps QV-062's `queued→running→succeeded/failed` lifecycle (idempotent via `mark_running` + `run_key` ledger) and now hands the engine a `BacktestDataAccess(session)`. Per-tenant concurrency cap + fine-grained progress %-streaming are **infra/UI concerns** (worker config; a `progress` column would need a migration + QV-071 UI) — out of scope here; coarse progress is the existing `started_at`/`finished_at` + status transition. Reads are global PIT reference data, so the privileged-session pattern (QV-062) is retained.
   [Source: `06` §4 (queues, per-tenant caps); QV-062 `jobs/backtest.py` lifecycle]

7. **Tests + gates** — a real-Postgres integration test on a deterministic synthetic panel proving: the loop runs and returns typed metrics; **determinism** (same spec twice → identical metrics); **frictions bite** (`costs_bps>0` < `costs_bps=0`); **survivorship-free** (a member later delisted is included and force-exited at last price); **benchmark computed**; cadence changes `n_rebalances`. Plus the `run_backtest` job moves `queued→succeeded` with metrics. Coverage ≥80% on new code; full-tree gates green (ruff, ruff format, **bare `mypy`**, lint-imports **3/3**, bandit, pip-audit). **No new table/migration/API.**
   [Source: testing rules; QV-063/064 real-PG precedent; QV-066 will generalise the bias guards]

---

## Dev Notes

### Placement & DAG (read this first)

- The engine lives in **`analytics/backtest.py`** (replace the `BacktestEngine.run` placeholder body; keep the `BacktestResult` dataclass shape — `metrics: dict`, `result_ref: str | None`). It reads through **`BacktestDataAccess`** (`analytics/backtest_data.py`). `analytics → market_data` is a kept DAG contract; the engine imports `trading_calendar` from `market_data` (allowed).
- **CRITICAL DAG BOUNDARY:** `analytics` **may NOT import `portfolio`** (layer order is `portfolio → analytics`; upward imports are forbidden). QV-053's constraints engine is `portfolio/constraints.py` — **do not import it.** The backtest sizes weights **inline (equal-weight)**; QV-053 is a conceptual dependency only. Same for `portfolio/risk.py` — compute metrics inline with **numpy** (already a dep; see `market_data/returns.py`). Confirm `lint-imports` stays **3/3**.
- Inject the seam: change `BacktestEngine` to hold a `BacktestDataAccess` (e.g. `BacktestEngine(data)`), and in `jobs/backtest.py::_run` construct `BacktestEngine(BacktestDataAccess(session)).run(spec)`. Keep the `run(spec) -> BacktestResult` signature otherwise.
- Python 3.13, mypy strict — **run bare `mypy`** (it includes `scripts`; `mypy src tests` false-flags, per QV-063). Money/ratios are `Decimal`; only cross into float inside numpy (as the risk/returns layers do), then serialise back to `str`.

### Reuse — do NOT re-implement

- **Universe / ranking / returns / last-price** are all QV-063/064 — call them, never re-query:
  - `data.universe_as_of(D, index_code="NIFTY200", market="NSE")` → survivorship-free members at `D`.
  - `data.ranked_universe(D, universe, rank_by=…, top_n=…)` → PIT top-N ids.
  - `data.returns_as_of(D, stock_ids, lookback_days=…)` → `ReturnsMatrix(values, stock_ids, dates, dropped)` of **simple adj-close returns** aligned to common dates.
  - `data.last_price_as_of(D, stock_ids)` → `{id: (date, Decimal)}` last valid bar ≤ `D` for forced exits.
- **`market_data.trading_calendar.sessions_in_range(start, end)`** → the ordered session dates; bucket by cadence for rebalance dates and use consecutive sessions for the return periods. `last_completed_session` clamps `end` if needed.
- **`ReturnsMatrix`** already drops thin names and reports them (`dropped`) — a dropped held name is a force-exit candidate (AC-4).
- **`analytics.scoring.MODEL_VERSION`** (`"score-v1"`) is the methodology fingerprint for the row's `model_version`.

### Repo tweak (small, backward-compatible)

`analytics/backtests.py::mark_succeeded(session, id, *, metrics, result_ref)` does not persist `model_version`/`weights_version`. Extend it with two optional kwargs (default `None`) and set the columns in the `UPDATE` (they exist on the table, migration `0011`). Keep existing callers working. Do **not** add columns/migrations.

### The rebalance loop (reference algorithm — deterministic)

1. `dates = sessions_in_range(spec.start, spec.end)`; `rebalance_dates` = the first session of each weekly/monthly/quarterly bucket within `dates`.
2. State: `weights: dict[UUID, Decimal]` (held), `equity = Decimal(1)`, `curve = [equity]`, `turnovers = []`.
3. For each period between consecutive session dates `t → t+1`: `equity *= (1 + Σ_i weights[i] · r_i(t+1))`, where `r_i` from an `adj_close` panel (use `returns_as_of` at the period boundary, or build a per-name adj-close series once and diff). Append to `curve`.
4. On a rebalance date `D`: recompute target = equal-weight over `ranked_universe(D, universe_as_of(D), …)`; `turnover = ½·Σ|target − held|`; `equity *= (1 − turnover·(costs_bps+SLIPPAGE_BPS)/1e4)`; record turnover; set `held = target`.
5. **Delisting:** before applying a period return, any held name absent from the current `universe_as_of` / with no bar is realised to cash at `last_price_as_of` and removed from `held` (weight → cash, contributing 0 return thereafter until next rebalance).
6. Benchmark: same loop with a fixed equal-weight `universe_as_of(spec.start)` buy-and-hold, no rebalances/costs.
7. Metrics from `curve`: `total_return = curve[-1]-1`; `cagr` annualised by `dates` span; `ann_vol = std(period_returns)·√252`; `sharpe = mean/std·√252` (guard std=0); `max_drawdown = min(curve/cummax − 1)`; `avg_turnover = mean(turnovers)`. Serialise every value with `str(Decimal(...).quantize(...))`.

> Keep it readable and correct over clever. A precise, well-tested equal-weight loop is the deliverable; weighting schemes/constraints/richer metrics are later stories.

### Queue routing

Add to `jobs/celery_app.py` `task_routes`: `"quantvista.run_backtest": {"queue": "user"}` (alongside the existing `score_news → nlp`). No enqueue-site change — `core.tasks.enqueue`/`send_task` routes by name. Per-tenant concurrency cap = worker deploy config (documented; dev has no worker — Docker/worker deferred).

### Scope boundary (do NOT pull these in)

- **Full metrics suite** (Sortino, hit rate, exposure-over-time, richer risk) = **QV-068**. QV-065 ships the core set above.
- **Parquet/DuckDB result artifact** (`result_ref`) = **QV-067**. QV-065 leaves `result_ref=None` (metrics live in the JSONB).
- **Bias-regression CI suite** (permanent counterfactual guards) = **QV-066**. QV-065's test proves loop mechanics + frictions + determinism + a survivorship/forced-exit case.
- **Frontend setup/results UI** = **QV-071**. No API change here (POST/GET already exist from QV-062).
- **Reproducibility guarantee formalisation** = **QV-069**. QV-065 stores `model_version`/`weights_version` and is deterministic.

### Previous-story / epic intelligence

- **QV-064 (just merged, PR #73)** added `universe_as_of` + `last_price_as_of` to `BacktestDataAccess`, completing the seam. **QV-063** built `ranked_universe`/`returns_as_of` and set the rule: "the engine reads through this seam only; no `latest` read." QV-065 is the first real consumer — honour that discipline exactly.
- Real-PG regression pattern (QV-063/064): seed a synthetic universe + `daily_prices` + `index_constituents` on `admin_engine` inside a rolled-back transaction (no residue), bind a `Session` to the same connection, assert on the engine output. `run bare mypy`; `scripts` is an importable package.
- `jobs/backtest.py` already handles idempotency (`mark_running` only fires on a queued row; ledger skips a re-run); QV-065 just swaps the placeholder call for `BacktestEngine(BacktestDataAccess(session)).run(spec)` and extends `mark_succeeded` with the versions.

### Git intelligence (recent)

`fc0ff2c QV-064 #73` · `3517e40 QV-063 #72` · `541b4e1 QV-062 #71`. The QV-063/064 integration tests are the closest templates for the synthetic-panel fixture; `tests/test_backtest_engine.py` (QV-062) currently asserts the placeholder — update it for the real engine.

### Project context reference

`_bmad-output/project-context.md` — backend `backend/src/quantvista/<context>/`; import-linter `root_package = quantvista`; **PIT correctness is the cardinal rule of Epic 8**; money as `Decimal` via `str`; yfinance dev-only.

## Tasks / Subtasks

### Task 1: Engine core — rebalance loop (AC-1, AC-2)
- [x] Rewrite `BacktestEngine` in `analytics/backtest.py` to take a `BacktestData` (Protocol, satisfied by `BacktestDataAccess`); build the cadence schedule via `sessions_in_range`; run the equal-weight top-N loop reading only through the seam. Keep `BacktestResult` shape.
- [x] Update `jobs/backtest.py::_run` to `BacktestEngine(BacktestDataAccess(session)).run(spec)`.

### Task 2: Frictions (AC-3)
- [x] Turnover = ½·Σ|Δw| per rebalance; deduct `turnover·(costs_bps+SLIPPAGE_BPS)/1e4` from equity; `SLIPPAGE_BPS` documented constant; report `avg_turnover`.

### Task 3: Adjusted returns + delisting forced exit (AC-4)
- [x] Returns from `adj_close` via a per-name `price_panel` (new seam method — see Debug Log for why not `returns_as_of`); a held name with no bar at a session is realised to cash and force-exited via `last_price_as_of`, not dropped/zeroed.

### Task 4: Benchmark + core metrics + versions (AC-5)
- [x] Equal-weight buy-and-hold benchmark of `universe_as_of(start)`; compute the core metric set; serialise Decimals as strings.
- [x] Extend `analytics/backtests.py::mark_succeeded` with optional `model_version`/`weights_version`; engine sets `MODEL_VERSION` + `"equal-weight-v1"`.

### Task 5: Queue routing (AC-6)
- [x] Add `"quantvista.run_backtest": {"queue": "user"}` to `celery_app.task_routes`; documented the per-tenant cap as a worker-deploy concern.

### Task 6: Tests + gates (AC-7)
- [x] New `tests/integration/test_backtest_engine_run.py` (real PG): the new `price_panel`/`adjusted_close_panel` reader — per-name, PIT-bounded, non-intersecting for a delisted name — + `BacktestDataAccess` satisfies the `BacktestData` Protocol.
- [x] Rewrote `tests/test_backtest_engine.py` (9 unit tests via a scripted `FakeData`): typed core metrics, determinism, frictions bite, cadence, degenerate range, benchmark/excess consistency, delisting forced-exit spy, flat-price slippage. Updated `test_api_backtests.py` lifecycle assertion for the real engine (metrics populated, not `{}`).
- [x] Full-tree gates green; new-code coverage 99% (engine) / 100% (seam, repo helper). Story Status → review; sprint-status → review; Dev Agent Record filled.

## Dev Agent Record

### Debug Log

- RED: rewrote `test_backtest_engine.py` against the intended Protocol-injected API → 7 failures (engine took no `data` arg, returned empty metrics).
- **Design call — `price_panel` over `returns_as_of`:** `returns_matrix_as_of` intersects dates across names, so a mid-run delisting would trim the *whole* panel to the delisted name's last date — breaking AC-4. Added a per-name, non-intersecting `adjusted_close_panel` repo reader + `BacktestDataAccess.price_panel` seam method; the engine walks that.
- **Protocol seam:** the engine depends on a `BacktestData` Protocol (not the concrete class) → precise, DB-free unit tests via a scripted `FakeData`, and mypy verifies `BacktestDataAccess` conforms.
- **DAG:** confirmed `analytics` does not import `portfolio` (lint-imports 3/3); weights are equal-weighted inline, metrics computed inline with numpy.
- **Slippage always applies** (AC-3: `costs_bps + SLIPPAGE_BPS`), so even a zero-commission run has a small drag — adjusted the flat-price test accordingly.
- Gate fixes: several docstring/comment E501s and one format nit → reworded/`ruff format`.
- Coverage: pushed engine 96%→99% with weekly-cadence + degenerate-range tests; the one remaining line is an empty-`_equal_weight` guard. repositories.py misses are pre-existing guards in unrelated functions.

### Completion Notes List

- **Deterministic factor-strategy rebalance loop** reading only through the QV-063/064 seam (no "latest" read) → look-ahead & survivorship structurally impossible. Cadence schedule from `sessions_in_range`; equal-weight top-N; hold on `adj_close` returns.
- **Frictions:** turnover = ½·Σ|Δw|, cost = `turnover·(costs_bps+SLIPPAGE_BPS)/1e4`; `avg_turnover` reported; frictions provably reduce return.
- **Delisting:** a held name with no bar is force-exited to cash via `last_price_as_of` (spied in the unit test).
- **Benchmark:** equal-weight buy-and-hold of `universe_as_of(start)` (internal PIT proxy; real Nifty200 TRI deferred). **Core metrics** (`total_return/cagr/ann_vol/sharpe/max_drawdown/avg_turnover/n_rebalances/benchmark_return/excess_return`) as Decimal strings; `model_version`/`weights_version` persisted.
- **`user` queue** route added; per-tenant cap documented as infra. Job keeps QV-062's idempotent lifecycle; the real end-to-end path is covered by `test_api_backtests.py::test_submit_poll_run_lifecycle`.
- Scope held: full metric suite (QV-068), Parquet artifact (QV-067), bias-regression CI (QV-066), UI (QV-071) all deferred.
- Full suite **724 passed / 5 skipped**; all gates green.

### File List

- `backend/src/quantvista/analytics/backtest.py` (rewritten — `BacktestData` Protocol + real `BacktestEngine` rebalance loop, frictions, benchmark, metrics)
- `backend/src/quantvista/analytics/backtest_data.py` (modified — `price_panel` seam method)
- `backend/src/quantvista/market_data/repositories.py` (modified — `adjusted_close_panel` reader + SQL)
- `backend/src/quantvista/analytics/backtests.py` (modified — `mark_succeeded` now persists `model_version`/`weights_version`)
- `backend/src/quantvista/jobs/backtest.py` (modified — wires `BacktestEngine(BacktestDataAccess(session))`, passes versions)
- `backend/src/quantvista/jobs/celery_app.py` (modified — `run_backtest` → `user` queue)
- `backend/tests/test_backtest_engine.py` (rewritten — 9 unit tests via scripted `FakeData`)
- `backend/tests/integration/test_backtest_engine_run.py` (new — real-PG panel reader + Protocol conformance)
- `backend/tests/integration/test_api_backtests.py` (modified — lifecycle assertion for the real engine)

### Change Log

- 2026-07-27 — QV-065 backtest engine core: deterministic factor-strategy rebalance loop (equal-weight top-N) with transaction costs + slippage + turnover, delisting forced-exit at last valid price, equal-weight benchmark proxy, core metrics (Decimal-as-string) + `model_version`/`weights_version`, all via the QV-063/064 PIT seam; `run_backtest` routed to the `user` queue. New per-name `price_panel` reader. 13 new tests; gates green; engine coverage 99%.

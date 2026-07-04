---
baseline_commit: 1c9f521a2af1758e314d80e21e07a442dcde2cae
---

# Story 3.13: QV-025 — Schema: technical_indicators (partitioned) + compute_indicators

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the analytics layer**,
I want **technical indicators computed daily from adjusted prices and stored point-in-time**,
so that **momentum / risk factors have trustworthy inputs — and the ingest → validate → indicators pipeline runs as a real event-driven DAG**.

> Canonical ID **QV-025** · Epic 3 (EPIC-DATA) · `[QUANT]` · 8pts · Sprint 02 · depends: **QV-014 ✅** (daily_prices), **QV-017 ✅** (adjusted close), **QV-024 ✅** (event bus)
> Authoritative: `plans/03` §4.1 (`technical_indicators` DDL) · `06` §3 + catalog (`compute_indicators`, key `ind:{market}:{date}`, emits `IndicatorsComputed`). First **real** event consumer — retires QV-024's synthetic-handler caveat.

## ⚠️ Read this first — the DDL already exists (verify, do NOT re-create)

`technical_indicators` is already defined in **`0006_indicators_factors_scores.py`** (applied; partitioned monthly by `date`, `UNIQUE (stock_id, date)`, columns: `sma_50, sma_200, ema_20, rsi_14, macd, macd_signal, bollinger_upper, bollinger_lower, atr_14, ret_3m, ret_6m, ret_12m, vol_30d, beta_1y`). **No new migration.** QV-025's net code is the Polars indicator computation + repository upsert + the `compute_indicators` task + the two pipeline event consumers.

## Locked decisions

- **Trigger = `PricesValidated` (gate-passed), not raw `PricesIngested`** (owner-confirmed; grounded in QV-018). QV-018 deliberately introduced `PricesValidated` (emitted by `DataQualityService` on gate-pass) as the downstream trigger — "indicators QV-025 will key off `PricesValidated`, not `PricesIngested`". We never compute on data that failed the quality gate.
- **Wire BOTH edges of the event chain now** (realizes the owner's DAG; QV-025 introduces the consumer-registration mechanism). Neither subscription existed before — QV-018 predates the subscribe-capable bus (it used the publish-only `LoggingEventBus`); QV-024 built the real bus:
  ```
  PricesIngested  ─▶ on_prices_ingested  ─▶ validate_prices.delay(market, date)   → PricesValidated / DataQualityGateFailed
  PricesValidated ─▶ on_prices_validated ─▶ compute_indicators.delay(market, date) → IndicatorsComputed
  ```
- **Thin consumers enqueue Celery tasks; the task does the heavy work.** The `PricesValidated`/`PricesIngested` handlers just `.delay(...)` the corresponding task — no heavy Polars work inside the (synchronous, in-process) publish call. `register_pipeline_consumers(bus)` subscribes both handlers on `get_event_bus()`, called from the worker composition root (and explicitly in tests).
- **Polars-vectorized compute; statistical indicators in `float64`, stored as `numeric`.** The plan mandates Polars (confirmed installs). Indicators are statistical quantities (RSI/MACD/vol/beta), so `adj_close` (`Decimal`) is read → `float64` for the math, then rounded to each column's `numeric(…)` precision on store. The **"money stays `Decimal`" rule is unaffected** — indicators are derived analytics, not monetary ledger values. Polars ships `py.typed` (no mypy override).
- **Compute from ADJUSTED close** (`adj_close`, QV-017) for SMA/EMA/RSI/MACD/Bollinger/returns/vol/beta — so splits/bonuses don't fake momentum. **ATR-14 uses raw `high/low/close`** (true range; a 14-session window rarely spans a split, and we don't store adjusted OHLC — noted, revisit if needed).
- **`beta_1y` vs an equal-weighted universe daily-return benchmark** (owner-confirmed option a). We ingest constituents, not the NIFTY index level, so the market proxy is the equal-weighted mean of the universe's daily returns; `beta = cov(stock_ret, mkt_ret) / var(mkt_ret)` over ~252 sessions. A real index-level series (future) refines it.
- **Insufficient history → NULL for that indicator.** Each indicator needs its window (e.g. `sma_200` → 200 sessions, `ret_12m`/`beta_1y` → 252); rows without enough history store `NULL` for those columns, not a wrong value.
- **Idempotent per `(market, date)`; global table → privileged engine.** `compute_indicators` computes one row per stock for the target `date` and upserts `ON CONFLICT (stock_id, date)`; re-running is a no-op-equivalent overwrite. Emits `IndicatorsComputed`. Partitions are monthly (exist / `create_month_partition`).

## Acceptance Criteria

1. **Schema conformance confirmed + documented.** Verify `0006` `technical_indicators` (columns, `NUMERIC` types, `UNIQUE (stock_id, date)`, monthly range partitioning, index). Record conformance in the Dev Agent Record. **No duplicate migration.**
2. **Indicator computation (Polars, adjusted).** A pure module computes, per stock for a target `date` from its price history: `sma_50`, `sma_200`, `ema_20`, `rsi_14`, `macd` (EMA12−EMA26), `macd_signal` (EMA9 of macd), `bollinger_upper/lower` (SMA20 ± 2·σ20), `atr_14` (mean true range, raw OHLC), `ret_3m/6m/12m` (63/126/252-session simple return), `vol_30d` (30-session daily-return σ, annualised ×√252), `beta_1y` (252-session cov/var vs the equal-weighted universe return). Adjusted close for all except ATR. Insufficient history → `NULL`. Unit-tested against known inputs.
3. **`compute_indicators(market, date)` task.** Loads the active universe + each stock's `adj_close`/OHLC history (≥252 sessions ending at `date`) + the market-proxy return series, computes the target-date row per stock, and **upserts** `technical_indicators` keyed `(stock_id, date)`. Under `run_job` (`run_key = ind:{market}:{date}`, QV-015; recorded in `jobs_runs`). Idempotent; emits `IndicatorsComputed`. Default `date = last_completed_session(today)`.
3. **Event-driven pipeline (both edges).** `register_pipeline_consumers(bus)` subscribes `on_prices_ingested` (→ `validate_prices.delay`) and `on_prices_validated` (→ `compute_indicators.delay`) on the shared bus; called at worker start. A published `PricesValidated` enqueues `compute_indicators` for the event's `(market, date)`; a `PricesIngested` enqueues `validate_prices`. This is the first real consumer(s) — no more synthetic handlers.
4. **Boundaries.** Computation + repository in `market_data` (reads `daily_prices`, writes `technical_indicators`); imports no yfinance; `market_data` stays a DAG leaf. Consumers/task in `jobs` (composition root). Polars added as a core dep. Global table → privileged engine.
5. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on new code. **Unit:** the Polars indicator math on a crafted series (SMA/EMA/RSI/returns known values; insufficient-history → NULL). **Integration** (real Postgres, seeded throwaway universe + a ≥252-session price history): `compute_indicators` writes one indicators row per stock with sane values + idempotent re-run (row count stable, values overwritten); emits `IndicatorsComputed`. **Consumers:** publishing `PricesValidated`/`PricesIngested` on the bus enqueues the right task with the right args (task patched); end-to-end `PricesValidated` → `compute_indicators` → row written (eager).

## Tasks / Subtasks

- [x] **Task 1 — verify schema conformance (§4.1)** (AC: #1)
  - [x] Read `0006` + `03` §4.1; field/constraint/partition conformance note in the Dev Agent Record. Confirm **no** migration change.
- [x] **Task 2 — Polars indicator computation** (AC: #2)
  - [x] `market_data/indicators.py`: `compute_indicators_for_date(prices: pl.DataFrame, target_date) -> pl.DataFrame` (one row per stock: the 14 indicator columns). `prices` = `stock_id, date, adj_close, high, low, close`. Vectorized rolling (`rolling_mean/std`, `ewm_mean`, `pct_change`, RSI via rolling gain/loss, MACD, Bollinger, ATR true-range, returns, `vol_30d`, `beta_1y` vs equal-weighted market return). `float64` math; insufficient window → `null`. Add `polars` dep.
  - [x] `tests/test_indicators.py`: crafted series → known SMA/EMA/RSI/returns; short series → NULLs.
- [x] **Task 3 — repository: history read + indicators upsert** (AC: #3)
  - [x] `repositories.py`: `price_history_for_indicators(session, stock_ids, end, sessions=300) -> rows` (stock_id, date, adj_close, high, low, close, most-recent `sessions` per stock ≤ end); `upsert_technical_indicators(session, rows) -> int` (`INSERT … ON CONFLICT (stock_id, date) DO UPDATE`, all 14 columns, `Decimal`/None).
- [x] **Task 4 — compute_indicators task + pipeline consumers** (AC: #3, #4)
  - [x] `jobs/compute.py` (new): `compute_indicators(market, date_iso=None)` task under `run_job` (`ind:{market}:{date}`) — universe → history → `compute_indicators_for_date` → `upsert_technical_indicators` → emit `IndicatorsComputed` via `get_event_bus()`. Add module to mypy untyped-decorator override.
  - [x] `jobs/consumers.py` (new): `on_prices_ingested(env)` → `validate_prices.delay(market, date)`; `on_prices_validated(env)` → `compute_indicators.delay(market, date)`; `register_pipeline_consumers(bus)` subscribes both. Wire `register_pipeline_consumers(get_event_bus())` into the worker init (`celery_app` `worker_process_init`).
- [x] **Task 5 — tests + gates + reconcile** (AC: #5)
  - [x] `tests/integration/test_compute_indicators.py` (seeded ≥252-session history): row-per-stock written, sane values, idempotent, `IndicatorsComputed` emitted. `tests/test_pipeline_consumers.py`: publish `PricesIngested`/`PricesValidated` → correct `.delay` args (patched); eager end-to-end `PricesValidated` → indicators row. Run all gates; reconcile QV-024 → done (already applied on this branch).

## Dev Notes

### Scope discipline
QV-025 = the `technical_indicators` verify + the Polars `compute_indicators` job + the two pipeline event consumers (first real consumers). **Not this story:** factors/scores that consume indicators (Epic 4 — `compute_factors`/`compute_scores`), the correction-handling self-heal proof (→ QV-027), a real NIFTY index-level series for beta (future refinement), scheduling on beat (→ PV-005). **No migration.**

### Indicator conventions (windows in trading sessions)
`sma_50/200`, `ema_20`, `rsi_14`, `macd`=EMA12−EMA26 + `macd_signal`=EMA9(macd), `bollinger`=SMA20±2σ20, `atr_14`=mean(true range,14) on **raw** OHLC, `ret_3m/6m/12m`=63/126/252-session simple return on **adj_close**, `vol_30d`=σ(daily adj returns,30)×√252, `beta_1y`=cov(stock,mkt)/var(mkt) over 252 vs equal-weighted universe return. Round to column precision on store (`sma numeric(18,4)`, `rsi numeric(9,4)`, `macd numeric(18,6)`, …). Insufficient history → NULL.

### Adjusted vs raw
adj_close (QV-017 split/bonus-adjusted) drives momentum/return/vol/beta so corporate actions don't fake signal. ATR-14 uses raw `high/low/close` (short window; adjusted OHLC not stored) — a documented, low-risk exception.

### The event chain (owner's DAG, both edges wired here)
`register_pipeline_consumers` subscribes on the shared `get_event_bus()`. Consumers are **thin** — `.delay()` the task (heavy Polars runs in the worker, not in the synchronous publish). Payloads: `PricesIngested`/`PricesValidated` carry `market` + `end` → `(market, date)`. In tests, Celery eager mode (`.apply`) or a patched `.delay` verifies enqueue; an end-to-end eager run proves `PricesValidated → compute_indicators → row`.

### Reuse map
- `active_universe`, `privileged_session_scope`, `run_job`/`run_key`/`JobResult`/`JobRunLedger`, `last_completed_session`, `get_event_bus()`, `validate_prices` (QV-018), `IngestRunFailed`/strict pattern.
- Upsert template: `upsert_daily_prices`/`upsert_shareholding` (`INSERT … ON CONFLICT … DO UPDATE`).
- Integration seed scaffold (throwaway market/stocks/constituents + `daily_prices`) — from `test_corporate_actions.py` / `test_data_quality.py`, extended to ≥252 sessions.

### Boundaries & gates
- `market_data/indicators.py` imports `polars` + stdlib only; `market_data` stays a DAG leaf (`lint-imports` 3/3). `jobs/compute.py` + `jobs/consumers.py` are composition roots. Add `quantvista.jobs.compute` to the mypy untyped-decorator override. Coverage ≥ 80% on the new compute + repo + consumers.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (122 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf; `indicators.py` imports only polars/stdlib) ·
  `pytest` → **253 passed, 4 skipped** (Kafka broker down + 3 promtool). Coverage 94 %; new:
  `market_data/indicators.py` **100 %**, `jobs/consumers.py` **100 %**, `jobs/compute.py` 86 %
  (uncovered = the NaN-scrub branch, empty-history branch, and the Celery task body — tested via `_run_compute`).
- **RED confirmed** first: `test_indicators.py` failed with `ModuleNotFoundError: quantvista.market_data.indicators`.

### Completion Notes List — Task 1 schema conformance (`0006` vs `03` §4.1)

**`technical_indicators` conforms — NO migration change.** `0006_indicators_factors_scores.py`: all 14
indicator columns (`sma_50/200`, `ema_20`, `rsi_14`, `macd`, `macd_signal`, `bollinger_upper/lower`,
`atr_14`, `ret_3m/6m/12m`, `vol_30d`, `beta_1y`) as `NUMERIC`; `UNIQUE (stock_id, date)`; **PARTITION BY
RANGE (date)** monthly (`_bootstrap_partitions`); index `(stock_id, date DESC)`; global (no RLS). No deviation.

### Completion Notes List — implementation

- **Polars indicator math** (`market_data/indicators.py`, 100 % cov): `compute_indicators_for_date` —
  vectorized rolling SMA/EMA/RSI-14/MACD/Bollinger/ATR-14/returns/vol/beta, one row per stock for the
  target date. From **adjusted** close (QV-017) for momentum/return/vol/beta; **raw OHLC** for ATR-14.
  Insufficient window → `null`. `beta_1y` regresses each stock vs the **equal-weighted universe return**
  (proxy — owner option a). Proven on crafted series: SMA/returns exact, constant→0 vol + flat Bollinger,
  rising ramp→RSI 100, single-stock→beta 1, short history→NULLs.
- **`compute_indicators(market, date)` task** (`jobs/compute.py`): universe → `price_history_for_indicators`
  (≥252-session lookback) → Polars compute → `upsert_technical_indicators` (`ON CONFLICT (stock_id, date)`)
  → emit `IndicatorsComputed`. Under `run_job` (`ind:{market}:{date}`), idempotent. NaN→None scrub before
  the numeric upsert. Verified end-to-end over real Postgres (260-session seed): row per stock, RSI 100 on
  the ramp, idempotent re-run (row count stable).
- **First real event consumers** (`jobs/consumers.py`, 100 % cov) — retires QV-024's synthetic-handler
  caveat. `register_pipeline_consumers` wires **both** DAG edges on the shared bus: `PricesIngested →
  validate_prices.delay`, `PricesValidated → compute_indicators.delay` (thin handlers enqueue; heavy work
  runs in the worker). Registered in `celery_app` `worker_process_init`. Verified: publishing each event
  enqueues the right task with `(market, date)` from the envelope.
- **Types:** indicators are statistical → `float64` compute, Postgres rounds into the `numeric` columns on
  store; the "money stays `Decimal`" rule (ledger values) is unaffected. `polars` added as a core dep
  (ships `py.typed` — no mypy override). **No security-reviewer** — internal compute, no auth/PII/user-input.
- **Not scheduled** on beat (→ PV-005); real NIFTY index-level series for beta is a future refinement.

### File List

**New**
- `backend/src/quantvista/market_data/indicators.py` — Polars indicator math.
- `backend/src/quantvista/jobs/compute.py` — `compute_indicators` task.
- `backend/src/quantvista/jobs/consumers.py` — pipeline event consumers + `register_pipeline_consumers`.
- `backend/tests/test_indicators.py` — indicator math (unit).
- `backend/tests/test_pipeline_consumers.py` — consumer→task enqueue (unit).
- `backend/tests/integration/test_compute_indicators.py` — compute job over real Postgres.

**Modified**
- `backend/src/quantvista/market_data/repositories.py` — `price_history_for_indicators` + `upsert_technical_indicators`.
- `backend/src/quantvista/jobs/celery_app.py` — register pipeline consumers at worker start.
- `backend/pyproject.toml` — `polars` core dep + mypy override for `quantvista.jobs.compute`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-025 status; QV-024 → done (housekeeping).

### Change Log

- **2026-07-04 — QV-025 technical_indicators + compute_indicators.** Verified the pre-existing `0006`
  partitioned schema (no migration) and shipped the Polars indicator computation (adjusted close;
  beta vs equal-weight universe proxy; insufficient-history→NULL), the idempotent `compute_indicators`
  job, and the **first real event consumers** wiring both edges of the ingest→validate→indicators DAG on
  the QV-024 bus. Proven over real Postgres (260-session seed) + crafted-series unit tests. 253 tests
  green, coverage 94 % (indicators + consumers 100 %); ruff/mypy-strict/import-linter clean. Retires
  QV-024's synthetic-handler caveat.

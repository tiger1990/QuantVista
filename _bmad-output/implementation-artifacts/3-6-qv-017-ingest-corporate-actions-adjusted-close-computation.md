---
baseline_commit: a6d9f747a9ff0299f355f72d2ab7e3919bb5d90b
---

# Story 3.6: QV-017 — ingest_corporate_actions + adjusted-close computation

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the analytics layer**,
I want **corporate actions (splits/bonuses/dividends) ingested and `daily_prices.adj_close` computed from raw `close` + those actions**,
so that **splits/bonuses don't fake momentum, backtests use a continuous adjusted series, and re-ingesting late actions safely recomputes the history**.

> Canonical ID **QV-017** · Epic 3 (EPIC-DATA) · `[DATA]` · 5pts · Sprint 01 · depends: **QV-016 ✅**
> Authoritative: `plans/06` (job `ingest_corporate_actions`, key `corpact:{market}:{date}`, emits `CorpActionsUpdated`), `plans/03` §5 ("adjusted prices computed, not trusted blindly; raw `close` retained"), `plans/05` §4 (momentum factors). Completes the `adj_close` **placeholder** QV-016 wrote.

## Locked decisions
- **`adj_close` = split/bonus-adjusted, NOT dividend-adjusted.** Per `03` §5 ("splits/bonuses don't fake momentum") the computed `adj_close` removes only split/bonus price discontinuities. Dividends are **ingested + stored** in `corporate_actions` but **not folded into `adj_close`** (a dividend-inclusive *total-return* series is a clean future add if a factor needs it — noted, not built).
- **Raw `close` is never touched.** Only `adj_close` is (re)computed. Recompute is deterministic from current `close` + current split/bonus rows → idempotent.

## Acceptance Criteria

1. **Ingest corporate actions.** A provider-agnostic service pulls `provider.get_corporate_actions(symbol, start, end)` for the active universe (open constituents, reusing QV-016's `active_universe` + `SymbolMapper`) and **upserts** into `corporate_actions` keyed `(stock_id, ex_date, action_type)` (the unique from `0003`) — re-ingest = no duplicates, fields refreshed. Splits, bonuses, dividends all stored (`action_type` + `ratio_or_amount` + `details` + `source`).
2. **Compute `adj_close` from raw `close` + split/bonus actions (`03` §5).** For each stock, `daily_prices.adj_close` = `close` × cumulative back-adjustment factor: for a split/bonus with ratio `R` on `ex_date E`, all prices with `date < E` are multiplied by `1/R` (cumulative across all such actions after the date). Rows on/after the latest split have factor `1.0` (`adj_close = close`). Computed with **exact `Decimal`** (never float). Raw `close` unchanged.
3. **Idempotent recompute (late actions).** Recompute is a pure function of the current `close` + current split/bonus rows, so re-running after a **late action** is ingested correctly re-adjusts the affected history; running twice is a no-op. Dividends do **not** affect `adj_close`.
4. **Run under the job framework.** A Celery task `ingest_corporate_actions(market, date?)` wrapped by `run_job` (`run_key = corpact:{market}:{date}`, QV-015), reusing QV-016's strict per-stock isolation (no-data ≠ error; unexpected error → run fails → retry) and aggregate report (`stocks_ok`, `stocks_no_data`, `stocks_failed`, `actions_upserted`, `stocks_adjusted`, `failures`). Backfill mode over a date range shares the code. Emits **`CorpActionsUpdated`** via the injected `IEventBus` (`LoggingEventBus` default).
5. **Pure, tested adjustment logic.** The back-adjustment factor math lives in a **pure helper** (`market_data/adjustments.py`) unit-tested independently (single split, multiple splits, no splits, ex-date boundary — the price *on* the ex-date is NOT adjusted; the day *before* is). The repository applies it to `daily_prices`.
6. **Provider-agnostic + boundaries.** The service imports no yfinance/pandas; provider/bus/mapper injected. `market_data` stays a DAG leaf (import-linter green). `corporate_actions`/`daily_prices` are global tables → **privileged** engine.
7. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green. Unit (adjustment math, upsert idempotency) + integration (ingest actions → upsert; recompute adj_close with a split → prices before ex-date halved, on/after unchanged; idempotent re-run; late-action re-adjust; dividend does NOT change adj_close; per-stock isolation). Fake provider/bus (no network); ≥80% coverage on new modules. Optional tiny live yfinance smoke (real splits) — manual.

## Tasks / Subtasks

- [x] **Task 1 — pure adjustment helper** (AC: #2, #5)
  - [x] `market_data/adjustments.py`: `split_adjustment_steps(splits) -> list[(ex_date, factor)]` where `splits` = `(ex_date, ratio)` sorted DESC and `factor` = cumulative `1/∏ratio` applying to `date < ex_date`. `Decimal` throughout. Unit-test: one split (2:1 → 0.5 before ex-date), two splits (cumulative), none (→ empty), and the ex-date boundary.
- [x] **Task 2 — repository: upsert actions + recompute adj_close** (AC: #1, #2, #6)
  - [x] `repositories.py`: `upsert_corporate_actions(session, stock_id, actions) -> int` (ON CONFLICT (stock_id, ex_date, action_type) DO UPDATE ratio_or_amount/details/source). `recompute_adjusted_close(session, stock_id) -> int` — reset `adj_close = close`, then for each `(ex_date, factor)` from the helper, `UPDATE daily_prices SET adj_close = close * :factor WHERE stock_id=:s AND date < :ex_date`. Reads split/bonus rows (`ratio_or_amount > 0`).
- [x] **Task 3 — CorporateActionIngestionService** (AC: #1, #3, #4, #6)
  - [x] `services.py`: `CorporateActionIngestionService(provider, event_bus, *, symbol_mapper)`; `ingest(market, start, end, *, index_code="NIFTY200") -> CorpActionReport`. Per stock (isolated): `get_corporate_actions` → `upsert_corporate_actions` → `recompute_adjusted_close`; tally; emit `CorpActionsUpdated`. Reuse `active_universe`. `CorpActionReport` dataclass.
- [x] **Task 4 — Celery task + backfill** (AC: #4)
  - [x] `jobs/ingest.py` (extend): `ingest_corporate_actions(market="NSE", date_iso=None)` → `run_job("ingest_corporate_actions", "corpact:{market}:{date}", ...)` wiring the yfinance provider + `yahoo_symbol` + `LoggingEventBus`; strict-failure raise (reuse `IngestRunFailed`). `backfill_corporate_actions(market, start, end)`. Not added to `beat_schedule` (→ PV-005 cadence note).
- [x] **Task 5 — tests + gates + reconcile** (AC: #7)
  - [x] Unit (`test_adjustments.py`) + integration (`test_corporate_actions.py`: ingest+upsert idempotent; adj_close after a split; idempotent recompute; late-action re-adjust; dividend-only → adj_close == close; per-stock isolation). Fake provider/bus, seeded throwaway universe + daily_prices rows, cleanup. Run all gates; reconcile QV-016 → done (housekeeping).

## Dev Notes

### Scope discipline
QV-017 = ingest corporate actions + compute split/bonus-adjusted `adj_close` (finishing the QV-016 placeholder), idempotent. **Not this story:** dividend/total-return adjustment (noted future), data-quality gates (QV-018), fundamentals/shareholding ingestion (own stories), the real event-bus consumer of `CorpActionsUpdated` (QV-024), scheduling the job (→ PV-005). `corporate_actions` + `daily_prices` **already exist** (`0003`/`0004`) — **no new migration**.

### Adjustment math (the core, `03` §5)
- A split/bonus ratio `R` on `ex_date E` scales the post-`E` price down by `R`; to keep history continuous, multiply pre-`E` prices by `1/R`. Cumulative: `adj_close[t] = close[t] × ∏ (1/R_i)` over all split/bonus actions with `ex_date_i > t`.
- **Boundary:** the price **on** `ex_date` is already the post-split price → factor `1.0` for `date >= E`; only `date < E` is adjusted (strict `<`).
- Apply as successive prefix `UPDATE`s (splits DESC): reset `adj_close=close`, then for each split refine `date < ex_date`. Exact via `Decimal` (never `exp(sum(ln))` float tricks). Idempotent (full recompute from `close` + current rows).
- The **yfinance dev adapter** produces `SPLIT` (from `.Stock Splits`, `ratio_or_amount` = split factor e.g. `2.0`) and `DIVIDEND` (amount); bonuses arrive as splits from Yahoo. Only `action_type IN ('split','bonus')` with `ratio_or_amount > 0` drive the adjustment; dividends are stored, not applied.

### What already exists / reuse (QV-016)
- `market_data/repositories.py`: `active_universe`, `UniverseStock`, `upsert_daily_prices` (mirror its upsert style for actions). `market_data/services.py`: `SymbolMapper`, `IngestReport`, `_identity_mapper`, per-stock isolation pattern. `market_data/adapters/yfinance_dev.py`: `get_corporate_actions` (returns `CorporateAction` DTOs), `yahoo_symbol`, exclusive-`end` handling already fixed. `jobs/ingest.py`: `run_job` wiring, `IngestRunFailed`, strict policy, `backfill_*` shape. `core/events.py`: `LoggingEventBus`. `core/db.py`: `privileged_session_scope`.
- `CorporateAction` DTO (`models.py`): `symbol, ex_date, action_type: CorporateActionType, ratio_or_amount: Decimal, details, provenance`.
- `corporate_actions` (`0003`): `id, stock_id FK, ex_date, action_type CHECK(split/bonus/dividend/rights/merger), ratio_or_amount numeric, details jsonb DEFAULT '{}', source, ingested_at`, UNIQUE `(stock_id, ex_date, action_type)`. `daily_prices.adj_close` numeric(18,4) (QV-016 set = raw close placeholder).

### Testing notes
- Reuse the QV-016 pattern: seed a throwaway market + stock + open constituent (unique index_code) + a few `daily_prices` rows (raw close), a `corporate_actions` split row; recompute; assert `adj_close`. Clean up (`daily_prices`/`corporate_actions`/stock/market by ids; `jobs_runs` by run_key). Fake provider returns canned `CorporateAction`s; fake bus records `CorpActionsUpdated`.
- Concrete adjustment test: closes `[100 @ D1, 100 @ D2, 50 @ D3]`, split `2.0 @ D3` → `adj_close = [50, 50, 50]` (D1/D2 before ex-date halved; D3 on ex-date unchanged). Idempotent re-run → same. Add a later split → history re-adjusts. Dividend-only stock → `adj_close == close`.
- AAA, behavior-named, ≥80% new-module coverage.

### Project Structure Notes
- **New:** `market_data/adjustments.py`; `tests/test_adjustments.py`, `tests/integration/test_corporate_actions.py`.
- **Modified:** `market_data/repositories.py` (+2 fns), `market_data/services.py` (+service + report), `jobs/ingest.py` (+task + backfill).
- **Housekeeping:** `sprint-status.yaml` QV-016 → done.

### References
- [Source: plans/sprints/sprint-01-data-backbone-i.md#QV-017] — story + AC (ingest splits/bonuses/dividends; compute adj_close from close+actions, raw retained; idempotent recompute).
- [Source: plans/03-data-architecture.md#5] — adjusted-close computed-not-trusted; raw close retained; correctness/look-ahead.
- [Source: plans/06-scheduler-and-jobs.md#2-job-catalog] — `ingest_corporate_actions` (key `corpact:{market}:{date}`, emits `CorpActionsUpdated`).
- [Source: backend/src/quantvista/market_data/{repositories,services,adapters/yfinance_dev,models}.py] — QV-012/016 pieces to reuse.
- [Source: backend/src/quantvista/jobs/ingest.py] — run_job wiring + strict policy + backfill.
- [Source: _bmad-output/project-context.md] — rules #1 (global tables), #3 (boundaries), #4 (PIT/no look-ahead), Decimal-not-float.
- Memory: [[market-data-provider-strategy]] (provider-agnostic; dividends/total-return deferred).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (95 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf; service imports no yfinance) ·
  `pytest --cov` → **172 passed** (11 new), TOTAL coverage **95 %** (new: adjustments 100 %,
  services 100 %, repositories 98 %, jobs/ingest 94 %).
- **Live smoke (real Yahoo, no DB):** `get_corporate_actions("RELIANCE.NS", 2020..2026)` → 8 actions
  (7 dividends + 1 split); the **2024-10-28 2:1 split** came back as `ratio=Decimal("2.0")`. Confirms the
  real adapter path (no exclusive-`end` issue — corporate actions read `.actions`, not a windowed history).

### Completion Notes List

- **Finishes the QV-016 `adj_close` placeholder.** Ingests splits/bonuses/dividends into `corporate_actions`
  (idempotent on `(stock_id, ex_date, action_type)`) and computes **split/bonus-adjusted** `adj_close` from
  raw `close` (`03` §5). **No new migration** (tables exist in `0003`/`0004`).
- **Adjustment math** in a pure, 100 %-covered helper (`market_data/adjustments.py`): cumulative
  `1/∏ratio` for `date < ex_date`; the ex-date price is unadjusted. Applied by the repo as successive
  prefix `UPDATE`s (reset `adj_close=close`, then refine), exact `Decimal`, idempotent.
  Verified: closes `[100,100,50]` + 2:1 split on D3 → `adj_close [50,50,50]`.
- **Decisions honored:** `adj_close` = split/bonus only; **dividends stored but NOT applied** (verified:
  a dividend-only stock keeps `adj_close == close`); raw `close` never touched; late-split re-adjusts the
  full history on recompute.
- **Reuses QV-016 seam:** provider-agnostic `CorporateActionIngestionService` (injected provider/bus/mapper,
  no yfinance import), `active_universe`, `run_job` (`run_key = corpact:{market}:{date}`), strict per-stock
  isolation + `IngestRunFailed`, `backfill_corporate_actions`, `LoggingEventBus`. Emits `CorpActionsUpdated`.
- **Not scheduled** (beat) — same PV-005 cadence deferral as prices. **No security-reviewer** — parameterized
  SQL, no auth/PII/user-input, internal-dev provider.
- **Housekeeping bundled:** QV-016 reconciled `review → done`.

### File List

**New**
- `backend/src/quantvista/market_data/adjustments.py` — pure split/bonus back-adjustment factors.
- `backend/tests/test_adjustments.py` — adjustment math unit tests.
- `backend/tests/integration/test_corporate_actions.py` — ingest + adj_close pipeline (fake provider, real PG).

**Modified**
- `backend/src/quantvista/market_data/repositories.py` — `upsert_corporate_actions` + `recompute_adjusted_close`.
- `backend/src/quantvista/market_data/services.py` — `CorporateActionIngestionService` + `CorpActionReport`.
- `backend/src/quantvista/jobs/ingest.py` — `ingest_corporate_actions` task + `backfill_corporate_actions`.
- `backend/tests/integration/test_ingest_task.py` — corp-action task test + `_FakeYf.get_corporate_actions`.

**Housekeeping (bundled)**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-016 → done; QV-017 status.

### Change Log

- **2026-07-03 — QV-017 corporate actions + adjusted close.** Ingest splits/bonuses/dividends into
  `corporate_actions`; compute split/bonus-adjusted `daily_prices.adj_close` from raw `close` (pure Decimal
  helper, idempotent, dividends stored-not-applied per `03` §5). Provider-agnostic service + Celery task +
  backfill reusing the QV-016 seam; emits `CorpActionsUpdated`. Live-verified the real `get_corporate_actions`
  path (RELIANCE 2024 2:1 split). 172 tests green, coverage 95 %; ruff/mypy-strict/import-linter clean.
  No new migration. Reconciled QV-016 → done.

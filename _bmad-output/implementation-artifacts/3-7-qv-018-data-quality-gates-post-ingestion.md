---
baseline_commit: 4b653f9af29ad0d7165ccc7e4c21a384de2a0166
---

# Story 3.7: QV-018 — Data-quality gates (post-ingestion)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **an operator**,
I want **ingested `daily_prices` validated by explicit data-quality gates before anything downstream consumes it**,
so that **we never compute indicators/factors/scores on missing, null, non-positive, or gappy price data — a bad ingest fails loudly and halts the pipeline instead of silently poisoning every score built on top of it**.

> Canonical ID **QV-018** · Epic 3 (EPIC-DATA) · `[DATA]` · 5pts · Sprint 01 · depends: **QV-016 ✅**
> Authoritative: `plans/06` §5 ("Data-quality gates: after ingestion, validate row counts vs expected universe size, null-rate thresholds, and price sanity (no negative/zero, gap checks). Failing a gate halts downstream and alerts rather than scoring on bad data") · `06` §1 (event-choreographed pipeline `PricesIngested → … → ScoresComputed`) · `06` §6 (data-quality gate failure is an alert condition). Completes the **validation deferred from QV-016** (decision 2a: QV-016 did NaN→None only; negative/absurd-price rejection + coverage/gap checks are this story).

## Locked decisions

- **The gate is a distinct guard step (task `validate_prices`), not folded into `ingest_daily_prices`.** `06` §1 models the pipeline as event-choreographed steps; the gate is the guard *between* ingestion and downstream compute. QV-016's `ingest_daily_prices` and its `PricesIngested` emission stay **untouched** — `PricesIngested` remains the raw "data landed" signal. The gate emits a **new `PricesValidated`** event on pass, which becomes the real downstream trigger (indicators QV-025 will key off `PricesValidated`, not `PricesIngested` — noted, not wired here).
- **"Alert" = emit `DataQualityGateFailed` event + structured error log + fail the run (strict).** There is no Sentry/Slack/PagerDuty channel yet (that is the observability/alerts work — QV-009 / QV-020 dashboards / the alerts epic). The **event is the seam** a real notifier subscribes to later. Failing the run (raising so `run_job` marks it `failed`, no retry-to-green on bad data) is the concrete "halts downstream, does not silently proceed."
- **Gates validate raw OHLCV only; `adj_close` is excluded** from null-rate and sanity. `adj_close` is (re)computed asynchronously by QV-017's corporate-action job and may legitimately lag a fresh price ingest — gating on it here would false-alarm. Raw `open/high/low/close/volume` are what a fresh ingest must get right.
- **Thresholds are named constants in a frozen `QualityThresholds`** (coverage ≥ 0.95, OHLCV null-rate ≤ 1%, missing-session rate ≤ 2%), **overridable per call** (backfill windows / tests pass their own). No `data_quality_config` table (YAGNI — externalize to config/DB only when a second consumer needs to tune it).
- **No new migration.** Gates *read* the existing `daily_prices` (`0004`) + `index_constituents` (`0003`). Read-only over global tables → **privileged** engine.

## Acceptance Criteria

1. **Four gates, evaluated over a run's `daily_prices` for the active universe** (open constituents of `index_code`, reusing QV-016's `active_universe`), for a date or date-window:
   - **G1 Coverage** — `stocks_with_data / expected_universe_size ≥ min_coverage` (default 0.95). A partial ingest (e.g. provider dropped 30% of symbols) fails; the violation lists the missing symbols (capped).
   - **G2 Null-rate** — `null_ohlcv_cells / total_ohlcv_cells ≤ max_null_rate` (default 0.01), over `open/high/low/close/volume`. `adj_close` excluded.
   - **G3 Price sanity** — **zero tolerance**: no row with `open/high/low/close ≤ 0`, and no OHLC-bound violation (`high < low`, `high < open`, `high < close`, `low > open`, `low > close`). Any occurrence fails.
   - **G4 Gap/continuity** — over `[start, end]`, `missing_session_slots / (expected_universe_size × expected_sessions) ≤ max_missing_session_rate` (default 0.02), where `expected_sessions = len(sessions_in_range(start, end))` from the NSE trading calendar. Catches holes that would break indicator lookback windows.
2. **Pure, independently-tested evaluator.** Gate math lives in a **pure helper** `market_data/quality.py` — `evaluate_quality(metrics: PriceQualityMetrics, thresholds: QualityThresholds) -> QualityReport` — with **no DB and no yfinance** imports. `QualityReport(passed: bool, violations: list[GateViolation])`; each `GateViolation` carries `gate`, `observed`, `threshold`, `detail`. Unit-tested per gate: clean pass, each gate tripped in isolation, boundary values (exactly at threshold passes), empty universe handled.
3. **Metrics gathered by one repository query.** `repositories.price_quality_metrics(session, stock_ids, start, end) -> PriceQualityMetrics` computes the aggregates (expected/observed stock counts, OHLCV null cells + total cells, non-positive-price rows, OHLC-bound violations, missing-session slots, sample missing symbols) via SQL over `daily_prices` — set-based, no per-row Python. Privileged engine.
4. **`DataQualityService` orchestrates + emits.** `DataQualityService(event_bus)`; `validate(market, start, end, *, index_code="NIFTY200", thresholds=QualityThresholds()) -> QualityReport`. Resolves the universe → `stock_ids` + `expected_universe_size`, computes `expected_sessions`, calls the repo, evaluates, and **emits exactly one event**: `PricesValidated` on pass, else `DataQualityGateFailed` (payload includes the violations). Returns the report. Imports no yfinance/pandas; `market_data` stays a DAG leaf.
5. **Run under the job framework, strict.** A Celery task `validate_prices(market="NSE", date_iso=None)` wrapped by `run_job` (`run_key = dq:prices:{market}:{date}`, QV-015; idempotent, recorded in `jobs_runs` with rows_in = stocks validated). On `not report.passed` it **raises `DataQualityGateError`** so the run is marked `failed` (halts downstream; no silent success). `validate_prices_range(market, *, start, end)` shares the code for backfill windows. Default date = `last_completed_session(today)` (same T-1 convention as ingest).
6. **Boundaries + provenance.** `quality.py` is a pure leaf (import-linter green); the service/job wire it. `daily_prices`/`index_constituents` are global → privileged engine. No new dependency. `PricesValidated`/`DataQualityGateFailed` topics are plain dict payloads on the existing `IEventBus` (`LoggingEventBus` default).
7. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on new modules. **Unit** (`test_quality.py`): each gate. **Integration** (`test_data_quality.py`, real Postgres, fake bus, seeded throwaway universe + `daily_prices`): clean universe → `passed`, `PricesValidated` emitted; missing stocks → G1 fails; injected NULLs → G2 fails; a `close ≤ 0` and an OHLC-bound violation → G3 fails; a mid-window missing session → G4 fails; a failing gate → `DataQualityGateError` from the task + `jobs_runs.status = failed` + `DataQualityGateFailed` emitted (not `PricesValidated`).

## Tasks / Subtasks

- [x] **Task 1 — pure gate evaluator** (AC: #1, #2)
  - [x] `market_data/quality.py`: frozen `QualityThresholds` (constants: `min_coverage=Decimal("0.95")`, `max_null_rate=Decimal("0.01")`, `max_missing_session_rate=Decimal("0.02")`), frozen `PriceQualityMetrics` DTO, frozen `GateViolation`, `QualityReport`. `evaluate_quality(metrics, thresholds) -> QualityReport` runs G1–G4, collecting a `GateViolation` per tripped gate; `passed = not violations`. Pure, exact `Decimal` ratios, no DB/yfinance. Guard the empty-universe case (expected 0 → no coverage/gap division by zero).
  - [x] `test_quality.py`: clean pass; G1/G2/G3/G4 each tripped alone; boundary (ratio exactly at threshold passes); empty universe.
- [x] **Task 2 — repository metrics query** (AC: #3, #6)
  - [x] `repositories.py`: `price_quality_metrics(session, stock_ids, start, end) -> PriceQualityMetrics`. Set-based SQL over `daily_prices` filtered by `stock_id = ANY(:ids)` and `date BETWEEN :start AND :end`: counts of distinct stocks with data, OHLCV null cells + total cells, non-positive-price rows, OHLC-bound-violation rows, observed (stock,date) slots (for gap math), and a capped sample of missing symbols. Expected stock/session counts passed in from the service (calendar-derived). Privileged session.
- [x] **Task 3 — DataQualityService** (AC: #1, #4, #6)
  - [x] `services.py`: `DataQualityService(event_bus)`; `validate(market, start, end, *, index_code="NIFTY200", thresholds=QualityThresholds()) -> QualityReport`. `active_universe` → `stock_ids` + `expected_universe_size`; `expected_sessions = len(sessions_in_range(start, end))`; `price_quality_metrics(...)`; `evaluate_quality(...)`; emit `PricesValidated` (pass) or `DataQualityGateFailed` (fail, with violation summary); return report. Structured log on failure.
- [x] **Task 4 — Celery task + backfill** (AC: #5)
  - [x] `jobs/quality.py` (new): `DataQualityGateError`; `_run_validate(market, start, end, key) -> JobOutcome` wraps `DataQualityService(LoggingEventBus()).validate(...)` in `run_job("validate_prices", key, ...)`, raising `DataQualityGateError` when `not passed` (rows_in = stocks_with_data). `validate_prices(market="NSE", date_iso=None)` task (`autoretry_for`, key `dq:prices:{market}:{date}`, default `last_completed_session`). `validate_prices_range(market, *, start, end)` (`dq:prices:{market}:backfill:{start}:{end}`). Not added to `beat_schedule` (→ PV-005 cadence, same as ingest).
- [x] **Task 5 — integration tests + gates + reconcile** (AC: #7)
  - [x] `tests/integration/test_data_quality.py`: seeded throwaway universe (unique `index_code`) + `daily_prices`; fake bus. Cases: clean → `passed` + `PricesValidated`; missing-stock → G1; NULL cell → G2; `close ≤ 0` + OHLC-bound → G3; mid-window missing session → G4; task raises `DataQualityGateError` + `jobs_runs.status=failed` + `DataQualityGateFailed` emitted. Cleanup by ids/run_key. Run all gates; reconcile QV-017 → done already applied (housekeeping check).

## Dev Notes

### Scope discipline
QV-018 = **post-ingestion validation gates** over `daily_prices` (coverage, null-rate, price sanity, gap), a pure evaluator + metrics query + service + strict guard task that halts downstream via a failed run and a `DataQualityGateFailed` event. **Not this story:** the real notifier/alert channel (Sentry/Slack — observability + alerts epics); the job dashboard + freshness-lag panels (→ QV-020); wiring downstream consumers to `PricesValidated` (→ QV-025 indicators); scheduling the gate on beat (→ PV-005); fundamentals/shareholding quality (their own stories); mutating/repairing bad data (gates *detect + halt*, they do not auto-fix). **No new migration.**

### Where the gate sits (the core design, `06` §1 + §5)
```
ingest_daily_prices ─▶ PricesIngested (raw landed, QV-016, unchanged)
                          │
                   validate_prices  ◀── THIS STORY
                     ├─ pass ─▶ PricesValidated ─▶ (downstream: indicators/factors — QV-025+)
                     └─ fail ─▶ DataQualityGateFailed (alert seam) + raise → run failed → HALT
```
- The gate is a **guard**, not a mutation: it reads `daily_prices`, decides pass/fail, and either green-lights downstream (`PricesValidated`) or stops the pipeline (failed run + alert event). This is the literal `06` §5 mechanism.
- Keeping QV-016 untouched matters: `PricesIngested` already has a test asserting its emission. Introduce `PricesValidated` as the *new* downstream trigger rather than moving QV-016's event.

### The four gates — rationale + exact math
- **G1 Coverage** — momentum/breadth factors need the whole universe; a silent 30% shortfall would skew every cross-sectional rank. `stocks_with_data / expected_universe_size ≥ 0.95`. Missing = `expected − with_data`; list a capped sample of missing symbols for the runbook.
- **G2 Null-rate** — QV-016 stores NaN→None, so nulls *can* land. A few are tolerable (halted sessions); a flood means a broken feed. `null_cells / total_cells ≤ 0.01` across `open/high/low/close/volume` (5 cells × rows).
- **G3 Price sanity** — a `≤ 0` or `high < low` price is never legitimate and would blow up returns/log-returns. **Zero tolerance**: any offending row fails the gate.
- **G4 Gap/continuity** — indicator lookbacks (SMA/RSI windows) break on holes. Over a window, `missing_slots / (universe × sessions) ≤ 0.02`, using `sessions_in_range(start,end)` (NSE calendar) for `expected_sessions`. For a single-date daily run `expected_sessions = 1` and G4 largely mirrors G1; it earns its keep on backfill windows.
- All ratios exact `Decimal`. Thresholds are `QualityThresholds` fields (overridable) — a wide backfill may pass looser `max_missing_session_rate`.

### Schema facts (read-only) — `daily_prices` (`0004`)
`stock_id uuid`, `date date`, `open/high/low/close/adj_close numeric(18,4)` (**nullable**), `volume bigint` (nullable), `source text`, `UNIQUE(stock_id, date)`, partitioned by month. Gate SQL: filter `stock_id = ANY(:ids) AND date BETWEEN :start AND :end`; `adj_close` **excluded** from null/sanity. `index_constituents` (`0003`) drives the universe via `active_universe` (open = `effective_to IS NULL`).

### Reuse map (do NOT re-invent)
- `active_universe(session, index_code, market)` → `list[UniverseStock]` (has `.stock_id`, `.symbol`, `.market`) — QV-016 repo.
- `sessions_in_range(start, end)` / `last_completed_session(as_of)` — `market_data/trading_calendar.py`.
- `run_job`, `run_key`, `JobResult`, `JobOutcome`, `JobRunLedger` — QV-015 (`jobs/framework.py`, `jobs/ledger.py`). Strict-raise pattern + `@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)` — mirror `jobs/ingest.py` (`IngestRunFailed`).
- `privileged_session_scope()` — `core/db.py`. `LoggingEventBus` — `core/events.py`. `IEventBus` — `core/interfaces.py`.
- Integration test scaffold (seed throwaway market/stocks/constituents/daily_prices under a unique `index_code`, fake bus, cleanup by ids/run_key) — copy the shape from `tests/integration/test_corporate_actions.py`.

### Boundaries & gates
- `quality.py` pure leaf (no `core`/DB/yfinance import needed — takes DTOs). `market_data` must stay a DAG leaf; `jobs/quality.py` is a composition root (may import `core`, `market_data`, `jobs.framework`). Confirm `lint-imports` stays 3/3.
- mypy `--strict`: annotate all signatures; frozen `@dataclass(slots=True)`; `Decimal` for ratios; per-module override for the `jobs.quality` Celery decorator only if the existing `jobs.ingest` override pattern is needed (check `pyproject.toml`).
- Coverage ≥ 80% on `quality.py`, the new repo fn, the service path, and `jobs/quality.py`.

### Optional live smoke (manual, no DB write beyond throwaway)
After the daily ingest against the real universe, run `validate_prices` for the last session and confirm `passed` (or an honest violation) — proves the gate on genuine Yahoo data. Not required for done.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN→refactor per task)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (99 files) ·
  `lint-imports` 3 kept/0 broken (`quality.py` stays a pure leaf; service imports no yfinance) ·
  `pytest --cov` → **189 passed** (17 new), TOTAL coverage **95 %** (new: `market_data/quality.py`
  100 %, `services.py` 100 %, `repositories.py` 98 %, `jobs/quality.py` 89 %).
- **Note on jobs/quality 89 %:** the 3 uncovered lines are the `validate_prices` daily-task body
  (resolves `last_completed_session(today())` + hard-codes `NIFTY200`), which can't be pointed at a
  throwaway test universe; `.name` registration is asserted and the shared `_run_validate` path is
  fully covered via `validate_prices_range` (success + strict-fail → `jobs_runs.status=failed`).
- **RED confirmed** first: `test_quality.py` failed with `ModuleNotFoundError: quantvista.market_data.quality`
  before the evaluator existed.

### Completion Notes List

- **Completes the validation deferred from QV-016 (decision 2a).** Four post-ingestion gates over
  `daily_prices` for the active universe: **G1 coverage** (stocks-with-data ÷ universe ≥ 0.95),
  **G2 null-rate** (OHLCV NULL cells ≤ 1 %), **G3 price sanity** (zero tolerance: no `≤0`, no
  OHLC-bound violation), **G4 gap/continuity** (missing (stock×session) slots ≤ 2 %, `expected_sessions`
  from `sessions_in_range`). **No new migration** — read-only over `daily_prices`/`index_constituents`.
- **Decisions honored:** the gate is a **distinct guard task** (`validate_prices`) — QV-016's
  `ingest_daily_prices` + `PricesIngested` untouched; pass emits the **new `PricesValidated`** (the real
  downstream trigger for QV-025), fail emits `DataQualityGateFailed` (the alert seam) + raises
  `DataQualityGateError` → run `failed` → pipeline halts. `adj_close` excluded from gates. Thresholds are
  `QualityThresholds` constants, overridable per call (a loose-threshold test proves a marginal backfill
  can pass).
- **Real-overlap caught by a live test:** a `close = 0` row trips **both** G3 checks (non-positive **and**
  `low > close`) — the metrics query counts it in both categories; the integration test asserts the honest
  detail string rather than a hand-guessed count.
- **Shape mirrors QV-016/QV-017:** pure evaluator + set-based metrics SQL + service returning a house-style
  `ValidationReport` + strict `run_job` task; provider-agnostic (`market_data` stays a DAG leaf). **No
  security-reviewer** — parameterized SQL, read-only, no auth/PII/user-input. **Not scheduled** on beat
  (→ PV-005 cadence, same as ingest).
- **Two implementation refinements over the literal AC/Task wording (design-only, behavior unchanged):**
  (1) the *service* returns a flat house-style `ValidationReport` (market/start/end + `passed` +
  `violations` + `stocks_validated`/`expected_stocks`) rather than the bare `QualityReport` named in AC4 —
  the *pure evaluator* still returns `QualityReport`; the wrapper carries the counts `run_job` needs for
  `rows_in` and matches `IngestReport`/`CorpActionReport`. (2) `price_quality_metrics` takes two extra
  keyword args beyond AC3's `(session, stock_ids, start, end)` — `expected_sessions` (calendar math stays
  in the service, so the repo remains pure SQL) and `missing_sample_cap=10` (bounds the missing-symbol
  sample so a large failure doesn't bloat the log/event payload). Same gates, decision, events, and halt.

### File List

**New**
- `backend/src/quantvista/market_data/quality.py` — pure gate evaluator (`QualityThresholds`,
  `PriceQualityMetrics`, `GateViolation`, `QualityReport`, `evaluate_quality`).
- `backend/src/quantvista/jobs/quality.py` — `validate_prices` task + `validate_prices_range` +
  `DataQualityGateError`, under `run_job` (`run_key = dq:prices:{market}:{date}`).
- `backend/tests/test_quality.py` — evaluator unit tests (per-gate, boundary, empty universe).
- `backend/tests/integration/test_data_quality.py` — gate pipeline over real Postgres (fake bus).

**Modified**
- `backend/src/quantvista/market_data/repositories.py` — `price_quality_metrics` (one set-based pass).
- `backend/src/quantvista/market_data/services.py` — `DataQualityService` + `ValidationReport`.
- `backend/pyproject.toml` — mypy untyped-decorator override extended to `quantvista.jobs.quality`.

### Change Log

- **2026-07-03 — QV-018 data-quality gates (post-ingestion).** Added four gates (coverage, null-rate,
  price sanity, gap/continuity) as a pure evaluator + set-based metrics query + `DataQualityService` +
  strict `validate_prices` task. Pass emits `PricesValidated` (new downstream trigger); fail emits
  `DataQualityGateFailed` and fails the run (halts the pipeline). Completes QV-016's deferred validation;
  no new migration. 189 tests green, coverage 95 %; ruff/mypy-strict/import-linter clean.

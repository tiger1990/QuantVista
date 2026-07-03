---
baseline_commit: 68e4aa61613bf15643fd780dd0b5bd3b4964fa54
---

# Story 3.5: QV-016 — ingest_daily_prices (idempotent, full universe)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **a daily job that pulls EOD OHLCV for the current index universe through the provider seam and upserts it into `daily_prices` — idempotent, per-stock-isolated, session-aware — plus a backfill mode over a date range**,
so that **analytics has trustworthy daily price history that is safe to re-run and swappable to a licensed vendor later without touching this code**.

> Canonical ID **QV-016** · Epic 3 (EPIC-DATA) · `[DATA]` · 8pts · Sprint 01 · depends: **QV-012 ✅, QV-014 ✅, QV-015 ✅**
> Authoritative: `plans/06` (job catalog: `ingest_daily_prices`, key `prices:{market}:{date}`), `plans/03` §4.1/§5 (`daily_prices`, adjusted-close-computed-not-trusted, survivorship). First real end-to-end pipeline: provider (QV-012) → job framework (QV-015) → `daily_prices` (QV-014).

## Locked decisions (from design discussion, 2026-07-03)
- **A — Failure policy: STRICT.** Per-stock isolation keeps the run going; **"no data" (holiday/delisted/empty) is NOT an error**. Any *unexpected* error marks the run **failed** → retried (idempotent upsert makes good stocks no-ops). Alert on repeated failure (`06 §1.4`).
- **B — Backfill: 5 years.** The **same task** takes a date window; an initial one-off 5y backfill run, then the scheduled job does **T-1**. (`06 §1.3`: backfill = same code, different window.)
- **C — `interval="1d"` on the provider API.** Extend `IMarketDataProvider.get_prices(symbol, start, end, interval="1d")`; the dev adapter supports only `"1d"` (rejects others). **`daily_prices` stays daily-only** (no schema change).
- **D — Real NSE trading calendar now.** Use `exchange_calendars` (**`XBOM`** = the India NSE/BSE calendar; they share holidays) behind a small `trading_calendar` helper to pick the last completed session (Yahoo is T-1) and drive the backfill window.
- **Provider strategy:** Yahoo/yfinance now (dev-only). **No stub "licensed vendor"** — the ingestion tests inject a fake `IMarketDataProvider` double, which already proves the seam. Real TrueData adapter + `providers` table + license gate defer to QV-072/073/076 (see [[market-data-provider-strategy]]).

## Acceptance Criteria

1. **Provider-agnostic ingestion service.** A `PriceIngestionService` takes an injected `IMarketDataProvider` + `IEventBus` (never the concrete yfinance class). It **must not** import or reference yfinance/pandas — swapping providers is a new adapter, zero service change (rule #8). `market_data` stays a DAG leaf (import-linter green).
2. **Universe = open index constituents.** Resolves the active universe from the DB — stocks with an **open** membership (`index_constituents.effective_to IS NULL`) for `index_code` (default `NIFTY200`), joined to `stocks` where `is_active`. Yields `(stock_id, symbol, market_code)`. Auto-scales 12 → ~200 when QV-019 lands (no code change).
3. **Per-provider symbol mapping.** A yfinance-owned mapper `yahoo_symbol(symbol, market) → e.g. RELIANCE + NSE → RELIANCE.NS` (`.BO` for BSE). The service passes the **mapped** symbol to the provider; the DB keeps the canonical `RELIANCE`. A future TrueData mapper is a new file, service unchanged.
4. **`interval` on the provider API (decision C).** `IMarketDataProvider.get_prices(symbol, start, end, interval="1d")`; `YFinanceDevProvider` honors `"1d"` and raises a clear error for any other interval (only daily supported today). Existing QV-012 tests updated for the new signature.
5. **Session-aware target date (decision D).** A `trading_calendar` helper over `exchange_calendars` `XBOM`: `last_completed_session(as_of) → date`, `is_session(date) → bool`. The daily job targets the **last completed session** (T-1 safe); backfill iterates sessions across the window. Wrap the library so `XBOM` is documented as the India NSE calendar.
6. **Idempotent upsert into `daily_prices` (`03` §4.1).** `DailyPriceRepository.upsert(stock_id, bars) → int` via `INSERT ... ON CONFLICT (stock_id, date) DO UPDATE` (open/high/low/close/volume/source; **`adj_close` = raw `close` placeholder** — the corporate-action-adjusted value is computed by QV-017, we do **not** trust the provider's Adj Close, `03` §5). Writes as the **privileged** engine (`daily_prices` is global). Re-running a date = **no duplicates** (upsert), values refreshed.
7. **Run under the job framework, strict failure (decisions A + job).** A Celery task `ingest_daily_prices(market, date?, ...)` wrapped by `run_job` (`run_key = prices:{market}:{date}`, QV-015). Per stock: `try` fetch+upsert; **empty/no-data → recorded as skipped (0 rows), not a failure**; an **unexpected exception → recorded as a failure**, isolated (loop continues). If **any** stock failed unexpectedly, the work raises so `run_job` marks the run **failed** (→ retried; the strict policy). Returns an **aggregate report** (`stocks_total`, `stocks_ok`, `stocks_no_data`, `stocks_failed`, `rows_upserted`, `failures: [(symbol, error)]`).
8. **`PricesIngested` event.** On a completed run, emit `PricesIngested` via the injected `IEventBus` (payload: `market`, `date`, `stocks_ok`, `rows_upserted`). A minimal **`LoggingEventBus`** (publish → structlog) is the default; the real Redis Streams bus is QV-024. Emitted before raising on partial failure? — emit the summary regardless (so downstream sees what *did* land), then raise if strict-failure applies.
9. **Backfill mode (decision B).** The task/service accepts a **date range** (`start`, `end`) and iterates the trading sessions in it (same per-stock upsert path). Backfill and daily share **one** code path (only the window differs). An initial **5-year** backfill is an operational run (documented), not the scheduled cadence.
10. **Deps + gates.** Add `exchange_calendars>=4` to runtime deps (calendar); confirm no yfinance in core/service. `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` all green. Tests use a **fake provider + fake event bus** (no network); real yfinance smoke is optional/manual. ≥80% coverage on new modules.

## Tasks / Subtasks

- [x] **Task 1 — interval on the provider API (decision C)** (AC: #4)
  - [x] `market_data/interfaces.py`: `get_prices(symbol, start, end, interval="1d")`. `adapters/yfinance_dev.py`: honor `"1d"`, raise `ValueError` for others. Update `tests/test_market_data_provider.py` for the signature. (Small edit to the QV-012 surface.)
- [x] **Task 2 — trading calendar helper (decision D)** (AC: #5)
  - [x] Add `exchange_calendars>=4` dep. `market_data/calendar.py` (or `core/`): wrap `XBOM` → `last_completed_session(as_of)`, `is_session(date)`, `sessions_in_range(start, end)`. Document `XBOM` = India (NSE/BSE) calendar. Unit-test against a known holiday (e.g. 2026-01-26 Republic Day → not a session).
- [x] **Task 3 — symbol mapper (yfinance-owned)** (AC: #3)
  - [x] `adapters/yfinance_dev.py`: `yahoo_symbol(symbol, market_code) → RELIANCE.NS / .BO`. Unit-test NSE/BSE mapping.
- [x] **Task 4 — DailyPriceRepository + universe resolver** (AC: #2, #6)
  - [x] `market_data/repositories.py`: `active_universe(session, index_code, market_code) → [(stock_id, symbol, market)]`; `upsert_daily_prices(session, stock_id, bars) → int` (ON CONFLICT (stock_id, date) DO UPDATE; adj_close = raw close placeholder). Privileged/global session.
- [x] **Task 5 — PriceIngestionService (decisions A, strict + report)** (AC: #1, #7, #8, #9)
  - [x] `market_data/services.py`: `ingest(market, target_date, *, index_code, provider, event_bus) → IngestReport` and `ingest_range(market, start, end, ...)` (shared per-stock path). Per-stock isolation; no-data=skip; error=failure; emit `PricesIngested`; raise on any unexpected failure (strict). `IngestReport` dataclass.
  - [x] Default `LoggingEventBus` implementing `core.interfaces.IEventBus` (publish → structlog). Location: `core/events.py`.
- [x] **Task 6 — Celery task + run_job wiring** (AC: #7)
  - [x] `jobs/ingest.py` (or extend celery_app): `ingest_daily_prices(market="NSE", date=None)` → resolves target session (calendar) → `run_job("ingest_daily_prices", "prices:{market}:{date}", work, ...)` with the yfinance dev provider + LoggingEventBus wired. Register the task; do NOT add to beat_schedule yet (real cadence lands with the live vendor / staging — note it).
- [x] **Task 7 — Tests (fake provider + fake bus, real Postgres)** (AC: #10)
  - [x] `tests/test_*` unit: symbol mapper; calendar (holiday); interval rejection. `tests/integration/test_price_ingestion.py`: seed a market+stock+open constituent; fake provider returns canned PriceBars → ingest → daily_prices rows upserted; **re-run → no dup** (row count stable, value refreshed); **per-stock failure isolated** (one symbol raises → run report shows failure, others upserted, run raises under strict); **no-data symbol → skipped, not failure**; event emitted (fake bus records). Clean up inserted rows + jobs_runs.
- [x] **Task 8 — Gates + reconcile + optional live smoke** (AC: #10)
  - [x] `ruff`/`ruff format`/`mypy`/`lint-imports`/`pytest`. Reconcile QV-015 → done (housekeeping, this branch). **Optional:** a tiny live yfinance smoke for 1–2 real symbols (network) to prove the real adapter path — manual, not in CI.

## Dev Notes

### Scope discipline
QV-016 = the daily EOD ingest pipeline (universe → provider → upsert → event), idempotent + strict + session-aware + backfill-capable, tested with fakes. **Not this story:** corporate-action-adjusted close (→ **QV-017**; we store raw close as the adj_close placeholder), data-quality gates (→ **QV-018**; QV-016 does only minimal sanity), the real Redis Streams event bus (→ **QV-024**; logging default now), the licensed TrueData adapter + `providers` table + license gate (→ **QV-072/073/076**), full NIFTY-200 population (→ **QV-019**; we ingest whatever is currently open). Beat *cadence* for this job is NOT scheduled yet (needs live staging / real vendor) — the task exists and runs on demand; scheduling is a later wiring step (note it, don't add to beat_schedule).

### What already exists / context to build on
- **`IMarketDataProvider`** (QV-012, `market_data/interfaces.py`): 5 methods; `get_prices(symbol, start, end)` — **add `interval="1d"`**. **`YFinanceDevProvider`** (`adapters/yfinance_dev.py`): `.history(start,end,auto_adjust=False)` → `PriceBar` DTOs (Decimal money, provenance `source='yfinance'`, `license_class=non_commercial_dev`). Add `yahoo_symbol()` here.
- **`PriceBar` DTO** (`market_data/models.py`): `symbol, date, open, high, low, close, adj_close, volume, provenance`. **Ignore the DTO's `adj_close` on write** (Yahoo's adjusted) — store raw `close` as the daily_prices adj_close placeholder (`03` §5 — compute-not-trust; QV-017 fills real adjustment).
- **`daily_prices`** (QV-014, migration `0004`): partitioned by month on `date`, UNIQUE `(stock_id, date)`, NUMERIC OHLC, `source`, `ingested_at`. Global (no RLS). `create_month_partition()` exists — a far-past backfill date may need its partition; **the DEFAULT partition (`daily_prices_default`) already absorbs any unpartitioned month**, so backfill works without pre-creating partitions (a maintenance job to add real monthly partitions is a later optimization).
- **Job framework** (QV-015): `run_key(*parts)`, `JobRunLedger`, `run_job(job_name, key, work, *, ledger, metadata)` — skip-if-succeeded, structlog, failure→re-raise. Reuse directly; `run_key = prices:{market}:{date}`.
- **`core/db.py`**: `privileged_session_scope()` for global-table writes (universe read + daily_prices write).
- **`core.interfaces.IEventBus`**: `publish(topic, event)` / `subscribe(...)`. Implement a `LoggingEventBus`.
- **Universe (seed):** 12 open NIFTY200 constituents; `stocks.symbol` = plain NSE tickers (`RELIANCE`, `TCS`, …), market `NSE`. So `yahoo_symbol` appends `.NS`.
- **Calendar:** `exchange_calendars` has **no `XNSE`** — use **`XBOM`** (India; NSE & BSE share the same trading holidays). Verified: 2026-01-26 (Republic Day) is not a session.

### Testing notes
- **No network in the suite.** Inject a **fake `IMarketDataProvider`** (returns canned `PriceBar`s per symbol; can be told to raise for one symbol, or return `[]` for a no-data symbol) and a **fake `IEventBus`** (records published events). Integration tests use real Postgres (`admin_engine`) but the ledger + daily_prices writes commit — so seed unique throwaway market/stock/constituent + a unique test date, and **clean up** (`DELETE FROM daily_prices WHERE date = <test>` + the `jobs_runs` run + the throwaway stock/market) in teardown.
- **Strict policy test:** one symbol's provider call raises → report shows it in `failures`, the *others* still upserted, and `run_job` marks the run failed (the work re-raises). A **no-data** symbol (provider returns `[]`) → counted in `stocks_no_data`, run still succeeds if nothing errored.
- **Idempotency test:** ingest a date twice → `daily_prices` row count unchanged; change a fake bar value + re-ingest → the row is updated (upsert), still one row.
- AAA, behavior-named, ≥80% coverage on new modules.

### Project Structure Notes
- **New:** `market_data/repositories.py` (fill), `market_data/services.py` (fill), `market_data/calendar.py`, `core/events.py` (`LoggingEventBus`), `jobs/ingest.py`; tests (`test_market_data_calendar.py`, `test_symbol_mapper.py`, `tests/integration/test_price_ingestion.py`).
- **Modified:** `market_data/interfaces.py` + `adapters/yfinance_dev.py` (+ its tests) for `interval`; `pyproject.toml` (`exchange_calendars`); possibly `core/interfaces.py` (no change needed — `IEventBus` exists).
- **Housekeeping on this branch:** `sprint-status.yaml` QV-015 → done.
- `market_data` imports only `core`/`schemas` (+ yfinance in the adapter, exchange_calendars in calendar). `jobs` (composition root) wires provider+bus into the task. Keep files 200–400 lines.

### References
- [Source: plans/sprints/sprint-01-data-backbone-i.md#QV-016] — story + AC (upsert (stock_id,date), re-run no dup, per-stock isolation, aggregate report, PricesIngested).
- [Source: plans/06-scheduler-and-jobs.md] — `ingest_daily_prices` catalog row, key `prices:{market}:{date}`, idempotent/backfill/fail-loud principles.
- [Source: plans/03-data-architecture.md] §4.1 (`daily_prices`), §5 (adjusted-close computed not trusted; survivorship), §1 (provider abstraction, provenance, monetization gate).
- [Source: backend/src/quantvista/market_data/{interfaces,models,adapters/yfinance_dev}.py] — QV-012 seam + DTOs to build on.
- [Source: backend/src/quantvista/jobs/{framework,ledger}.py] — QV-015 job framework to reuse.
- [Source: backend/src/quantvista/core/db.py] — `privileged_session_scope()`; [Source: core/interfaces.py] — `IEventBus`.
- [Source: _bmad-output/project-context.md] — rules #1 (global vs tenant), #3 (module boundaries), #4 (PIT/no look-ahead), #8 (licensing/provider seam); Decimal-not-float; jobs (run_key/idempotent/structured logs).
- Memory: [[market-data-provider-strategy]] (Yahoo-now/licensed-later, no stub vendor, interval-on-API, NSE calendar, 5y backfill, strict failure).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Verified against local **PostgreSQL 18.4** + native **Redis**; `exchange_calendars` `XBOM`.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (92 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf; service imports no yfinance) ·
  `pytest --cov` → **161 passed**, TOTAL coverage **95 %** (new modules: services/ingest/events
  100 %, repositories 96 %, trading_calendar 95 %, yfinance adapter 91 %).
- **Live yfinance smokes (real network):**
  1. `RELIANCE.NS` 10-day window → 8 real bars, close `1303.5` (Decimal), latest `2026-07-02`
     (confirms Yahoo's T-1 lag — the reason for the session calendar).
  2. **Full pipeline** for the seeded 12-stock NIFTY200, last session `2026-07-02`: **12/12 ok,
     12 rows** upserted (AXISBANK 1362.60, HDFCBANK 795.90, …), `PricesIngested` emitted; rows
     cleaned up (the real load is the operational 5y backfill, not a smoke).

### Completion Notes List

- **First real end-to-end pipeline:** universe (open constituents) → provider seam (QV-012) →
  job framework (QV-015) → `daily_prices` (QV-014). Proven live against real Yahoo.
- 🐛 **Live smoke caught a real bug the green tests missed:** **yfinance's `end` is EXCLUSIVE**,
  so a single-session fetch (`start==end`) returned **zero** bars — the daily job would silently
  ingest nothing. Fixed in the adapter (request `end + 1 day`, drop any bar past `end`) + a
  regression test (`test_get_prices_treats_end_as_inclusive`). Fake-provider tests couldn't catch
  this (they don't model Yahoo's date semantics) — exactly why the live run mattered.
- **Decisions implemented:** A strict failure (error→run fails+retry, no-data≠error, per-stock
  isolated + aggregate report); B backfill via `backfill_daily_prices` (same code, date window;
  5y is an operational run); C `interval="1d"` on the provider API (adapter rejects others, DB
  daily-only); D real NSE calendar via `exchange_calendars` `XBOM` (validated Republic Day).
- **Provider-agnostic:** the service imports **no** yfinance/pandas; provider + event bus + symbol
  mapper are injected. The Yahoo `.NS`/`.BO` mapper lives in the adapter; a TrueData mapper is a
  new file, service unchanged. `import-linter` confirms `market_data` stays a leaf.
- **adj_close = raw close placeholder** on ingest (we do NOT trust Yahoo's Adj Close; QV-017
  computes the corporate-action-adjusted value, `03` §5).
- **Idempotency:** `ON CONFLICT (stock_id, date) DO UPDATE` (row-level) + `run_key=prices:{market}:{date}`
  (job-level, QV-015). Re-run = no dup, values refreshed (tested).
- **`PricesIngested`** emitted via `LoggingEventBus` (Redis Streams bus = QV-024).
- **5y backfill + scheduling → PV-005 (decision: document + defer).** `backfill_daily_prices` is
  built and works (proven live for one session), but the actual **5-year historical load is not run**
  (`daily_prices` left empty) and the daily job is **not** in `beat_schedule`. Both are captured in
  **PV-005** with a runbook — a *deliberate operational deferral* (runnable here, held until analytics
  needs real history / a live scheduler exists), not environment-blocked.
- **Sanity validation fully deferred to QV-018 (decision 2a).** QV-016 does NaN→None only; negative/
  absurd-price rejection is left to the dedicated data-quality-gates story (QV-018). Clean separation.
- **No security-reviewer pass:** parameterized SQL throughout, no auth/PII/user-input; symbols come
  from the seeded DB, the provider is internal-dev-only, license labeled `non_commercial_dev`.
- **Housekeeping bundled:** QV-015 reconciled `review → done`.

### File List

**New**
- `backend/src/quantvista/market_data/trading_calendar.py` — NSE session calendar (XBOM wrapper).
- `backend/src/quantvista/market_data/repositories.py` — `active_universe` + idempotent `upsert_daily_prices`.
- `backend/src/quantvista/market_data/services.py` — `PriceIngestionService` + `IngestReport` (provider-agnostic).
- `backend/src/quantvista/core/events.py` — `LoggingEventBus` (default `IEventBus` until QV-024).
- `backend/src/quantvista/jobs/ingest.py` — `ingest_daily_prices` task + `backfill_daily_prices` (strict policy, run_job).
- `backend/tests/test_market_data_calendar.py` — calendar + symbol-mapper unit tests.
- `backend/tests/integration/test_price_ingestion.py` — service pipeline (fake provider/bus, real PG).
- `backend/tests/integration/test_ingest_task.py` — task wiring + strict-failure (monkeypatched provider).

**Modified**
- `backend/src/quantvista/market_data/interfaces.py` — `interval="1d"` on `get_prices`.
- `backend/src/quantvista/market_data/adapters/yfinance_dev.py` — `interval` guard, `yahoo_symbol` mapper, **exclusive-end fix**.
- `backend/tests/test_market_data_provider.py` — interval signature + exclusive-end regression test.
- `backend/pyproject.toml` — `exchange-calendars` dep + mypy overrides (exchange_calendars/pandas untyped, jobs.ingest decorator).

**Housekeeping (bundled)**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-015 → done; QV-016 status.

### Change Log

- **2026-07-03 — QV-016 ingest_daily_prices (first end-to-end pipeline).** Built the provider-agnostic
  `PriceIngestionService` (universe → provider seam → idempotent `daily_prices` upsert), the
  `ingest_daily_prices` Celery task + `backfill_daily_prices` under the QV-015 job framework (strict
  failure, per-stock isolation, aggregate report, `PricesIngested`), a real NSE trading calendar
  (`exchange_calendars` XBOM), the Yahoo symbol mapper, and `interval="1d"` on the provider API.
  Verified live against real Yahoo (12/12 seeded stocks) — which caught + fixed yfinance's exclusive-`end`
  bug. 161 tests green, coverage 95 %; ruff/mypy-strict/import-linter clean. Reconciled QV-015 → done.

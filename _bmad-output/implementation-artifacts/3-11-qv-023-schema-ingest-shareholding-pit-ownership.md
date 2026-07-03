---
baseline_commit: 15cf3ec31e37b9f9d0450cf5b2e488616b3489fc
---

# Story 3.11: QV-023 — Schema + ingest_shareholding (PIT ownership)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the analytics layer**,
I want **promoter / FII / DII / public holding (and pledged %) captured point-in-time per stock**,
so that **ownership factors (promoter-holding trend, pledge risk) have a correct time series to work from**.

> Canonical ID **QV-023** · Epic 3 (EPIC-DATA) · `[DATA]` · 3pts · Sprint 02 · depends: **QV-013 ✅** (stocks FK), **QV-012 ✅** (provider seam)
> Authoritative: `plans/06` §2 (job `ingest_shareholding`, Quarterly + poll, key `shp:{stock}:{quarter}`, **emits — / no event**) · `03` §4.1 (`shareholding` DDL: unique `(stock_id, as_of_date)`) · India-specific factors stay market-scoped (`future-us-market-expansion.md`).

## ⚠️ Read this first — the DDL already exists (verify, do NOT re-create)

`shareholding` is already defined in **`0005_fundamentals_pit.py`** (applied): `id, stock_id, as_of_date, promoter_holding, fii_holding, dii_holding, public_holding, pledged_pct` (`numeric(9,4)`), `source, ingested_at`, `UNIQUE (stock_id, as_of_date)`, `ix_shareholding_stock_id_as_of_date`. **No new migration.** QV-023's net code is a small upsert repository + the ingest service/task, mirroring QV-022.

## Locked decisions

- **PIT-by-date, not bitemporal.** Unlike fundamentals, shareholding has a single time axis: `as_of_date` (the quarter/observation date). Persistence is a plain **upsert keyed `(stock_id, as_of_date)`** (like `daily_prices`) — re-polling the same date updates in place; a new quarter is a new row. No `knowledge_from/to`, no versioning. (`ShareholdingSnapshot.as_of_date` is non-nullable, so every snapshot has a key.)
- **No event emitted (follow the `06` catalog).** The job catalog lists `ingest_shareholding` emits **—** (nothing). So the service takes **no event bus** and publishes nothing. A `ShareholdingUpdated` event is a trivial add when an ownership-factor consumer actually needs it (Epic 4) — YAGNI now; noted, not built. This is the one place the ingest-service shape intentionally differs from the price/corp-action/fundamentals services.
- **Provider-agnostic + strict per-stock isolation.** Same shape as the sibling ingest services: injected provider + mapper, imports no yfinance; one stock's failure never sinks the run (empty result = no-data ≠ error; unexpected error → failure → the job raises → retry). The dev adapter's `get_shareholding` is best-effort (Yahoo shareholding is sparse for India — often returns `[]`, i.e. no-data), so the **mechanism is fake-tested**; real FII/DII/pledge splits arrive with the licensed vendor (**QV-072**).
- **Global reference table → privileged engine.** `shareholding` carries no `tenant_id`/RLS (global, like `daily_prices`); repository uses `privileged_session_scope`. Percentages stay `Decimal`.

## Acceptance Criteria

1. **Schema conformance confirmed + documented.** Verify `0005` defines `shareholding` keyed `(stock_id, as_of_date)` with `promoter_holding`, `fii_holding`, `dii_holding`, `public_holding`, `pledged_pct` (all `NUMERIC`), `source`, `ingested_at`, and `ix_shareholding_stock_id_as_of_date`. Record the field/constraint conformance in the Dev Agent Record. **No duplicate migration.**
2. **Upsert repository.** `upsert_shareholding(session, stock_id, snapshots) -> int` — `INSERT … ON CONFLICT (stock_id, as_of_date) DO UPDATE` the five holding columns + `source` + `ingested_at = now()`; returns the number of rows written. Percentages `Decimal`. Idempotent: re-upserting the same `(stock_id, as_of_date)` updates in place (no duplicate row).
3. **Ingest service.** `ShareholdingIngestionService(provider, *, symbol_mapper=_identity_mapper)`; `ingest(market, *, index_code="NIFTY200") -> ShareholdingReport` pulls `provider.get_shareholding(symbol)` for the active universe, upserts per stock (isolated), tallies `stocks_ok` / `stocks_no_data` (empty result) / `stocks_failed` / `rows_upserted` / `failures`. Imports no yfinance; **no event**.
4. **Run under the job framework, strict.** A Celery task `ingest_shareholding(market="NSE", date_iso=None)` wrapped by `run_job` (`run_key = shp:{market}:{date}`, QV-015; recorded in `jobs_runs`), strict per-stock isolation (any unexpected failure → run `failed` → retry). Default poll date = `last_completed_session(today)`. Not added to `beat_schedule` (→ PV-005 cadence).
5. **Boundaries.** Service imports no yfinance/pandas; `market_data` stays a DAG leaf; global table → privileged engine. No new dependency, **no migration**.
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on new code. **Integration** (real Postgres, fake provider, seeded throwaway universe, cleanup): insert → row present with the holding values; idempotent re-run (same `(stock, as_of_date)` → updated in place, row count unchanged); a new `as_of_date` → a second row; empty provider result → `stocks_no_data` (no row); per-stock isolation (one provider raises → `stocks_failed=1`, others ingested); the task path via `run_job` (`jobs_runs` recorded; strict-fail → run `failed`).

## Tasks / Subtasks

- [x] **Task 1 — verify schema conformance (§4.1)** (AC: #1)
  - [x] Read `0005_fundamentals_pit.py` (shareholding block) + `03` §4.1; produce a field/constraint conformance note (columns, `NUMERIC` types, `UNIQUE (stock_id, as_of_date)`, index) in the Dev Agent Record. Confirm **no** migration change needed.
- [x] **Task 2 — upsert repository** (AC: #2, #5)
  - [x] `market_data/repositories.py` (extend): `upsert_shareholding(session, stock_id, snapshots: Sequence[ShareholdingSnapshot]) -> int` — `INSERT INTO shareholding (stock_id, as_of_date, promoter_holding, fii_holding, dii_holding, public_holding, pledged_pct, source) VALUES … ON CONFLICT (stock_id, as_of_date) DO UPDATE SET … , ingested_at = now()`. Returns `len(snapshots)`; `[]` → 0.
- [x] **Task 3 — ShareholdingIngestionService + task** (AC: #3, #4)
  - [x] `market_data/services.py` (extend): `ShareholdingReport` frozen dataclass + `ShareholdingIngestionService(provider, *, symbol_mapper=_identity_mapper)`; `ingest(market, *, index_code="NIFTY200") -> ShareholdingReport`. `active_universe` → per stock (isolated): `get_shareholding` → `upsert_shareholding`; tally (`ok` if ≥1 row, else `no_data`; `failed` on exception). No event.
  - [x] `jobs/ingest.py` (extend): `SHP_JOB_NAME`; `_run_shareholding(market, key, index_code)` wrapping the service in `run_job`, strict-raise on `stocks_failed` (reuse `IngestRunFailed`). `ingest_shareholding(market="NSE", date_iso=None)` task (`run_key shp:{market}:{date}`, default `last_completed_session`). No beat entry.
- [x] **Task 4 — integration tests + gates + reconcile** (AC: #6)
  - [x] `tests/integration/test_shareholding_ingest.py`: fake provider, seeded throwaway universe (unique `index_code`) + stocks, cleanup by ids/run_key. Cover insert; idempotent same-date upsert (row count unchanged, values updated); new-date second row; empty → no_data; per-stock isolation; task via `run_job` (success + strict-fail → `jobs_runs.status=failed`). Run all gates; reconcile QV-022 → done (already applied on this branch).

## Dev Notes

### Scope discipline
QV-023 = verify the pre-existing `shareholding` schema + a PIT-by-date upsert repository + the ingest service/task. **Not this story:** ownership factors that consume it (Epic 4), a `ShareholdingUpdated` event (add when a consumer needs it — the `06` catalog emits none), the licensed vendor supplying real FII/DII/pledge splits (→ QV-072), scheduling on beat (→ PV-005). **No migration** — do not touch `0005` (immutable history).

### Reuse map (mostly wiring)
- `ShareholdingSnapshot` (QV-012): `symbol, as_of_date (date, non-null), promoter_holding, fii_holding, dii_holding, public_holding, pledged_pct, provenance` → the upsert columns 1:1.
- `active_universe`, `SymbolMapper`/`_identity_mapper`, per-stock isolation loop, `IngestReport`-style report — copy from `PriceIngestionService`/`FundamentalsIngestionService` (but **drop the event bus** — no event here).
- `run_job`, `run_key`, `JobResult`, `IngestRunFailed`, `@app.task(...)`, `YFinanceDevProvider`, `yahoo_symbol`, `last_completed_session` — mirror `ingest_fundamentals` in `jobs/ingest.py`.
- `upsert_daily_prices` in `repositories.py` is the closest template for `upsert_shareholding` (executemany INSERT … ON CONFLICT).
- Integration scaffold (seed throwaway market/stocks/constituents under a unique `index_code`, fake provider, cleanup) — copy from `tests/integration/test_fundamentals_ingest.py`.

### Schema facts — `shareholding` (`0005`, read/write)
`id bigint PK`, `stock_id uuid FK stocks`, `as_of_date date NOT NULL`, `promoter_holding/fii_holding/dii_holding/public_holding/pledged_pct numeric(9,4)`, `source text`, `ingested_at timestamptz DEFAULT now()`, `UNIQUE (stock_id, as_of_date)`, `ix_shareholding_stock_id_as_of_date (stock_id, as_of_date DESC)`. Global (no RLS).

### The no-event decision
`06` §2 lists `ingest_shareholding` emits **—**. So — unlike every sibling ingest — the service publishes nothing and takes no `event_bus`. Keep it that way; a `ShareholdingUpdated` topic is a one-line add if/when an ownership-factor consumer subscribes (Epic 4). The dev adapter's `get_shareholding` is sparse (Yahoo, India) and frequently returns `[]` (no-data) — the fake provider supplies concrete snapshots to exercise the upsert.

### Boundaries & gates
- Service in `market_data/services.py` imports the repo + `core`; no yfinance/pandas; `market_data` stays a DAG leaf (`lint-imports` 3/3). `jobs/ingest.py` already has the untyped-decorator mypy override. Coverage ≥ 80% on the new repo fn + service + task path. Percentages stay `Decimal`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (110 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf; service imports no yfinance) ·
  `pytest` → **229 passed, 3 skipped** (promtool, QV-020), coverage **96 %** — `services.py` **100 %**,
  `repositories.py` 98 %, `jobs/ingest.py` 88 % (uncovered = the daily-task bodies resolving
  `last_completed_session(today)` + hard-coded NIFTY200, exercised via the `_run_*` runners).
- **RED confirmed** first: `test_shareholding_ingest.py` failed with
  `ImportError: cannot import name '_run_shareholding' from quantvista.jobs.ingest`.

### Completion Notes List — Task 1 schema conformance (`0005` shareholding vs `03` §4.1)

**`shareholding` conforms — NO migration change.**

| AC requirement | `0005_fundamentals_pit.py` | ✓ |
|---|---|---|
| keyed `(stock_id, as_of_date)` | `UNIQUE (stock_id, as_of_date)` | ✓ |
| `as_of_date` | `as_of_date date NOT NULL` | ✓ |
| ownership % (`NUMERIC`) | `promoter_holding/fii_holding/dii_holding/public_holding/pledged_pct numeric(9,4)` | ✓ |
| provenance + timing | `source text`, `ingested_at timestamptz DEFAULT now()` | ✓ |
| lookup index | `ix_shareholding_stock_id_as_of_date (stock_id, as_of_date DESC)` | ✓ |
| global (no RLS) | no `ENABLE ROW LEVEL SECURITY` → privileged engine | ✓ |

No deviation; no forward `0014_*` needed.

### Completion Notes List — implementation

- **PIT-by-date upsert** (`upsert_shareholding`, `repositories.py`): `INSERT … ON CONFLICT (stock_id,
  as_of_date) DO UPDATE` the five holding columns + `source` + `ingested_at=now()`. Re-polling a quarter
  updates in place (verified: 50 → 55, still one row); a new quarter is a second row.
- **`ShareholdingIngestionService`** mirrors the sibling ingest services (provider-agnostic, per-stock
  isolated) but takes **no event bus and emits nothing** — the `06` catalog lists no event for
  shareholding. `stocks_no_data` on an empty result (the norm — Yahoo shareholding is sparse for India);
  strict per-stock isolation; `ingest_shareholding` task under `run_job` (`run_key = shp:{market}:{date}`,
  not on beat → PV-005). Verified: success + strict-fail → `jobs_runs.status=failed`.
- **Dev provider is sparse** (frequently `[]`) → the mechanism is fake-tested with concrete snapshots;
  real FII/DII/pledge splits arrive with the licensed vendor (QV-072). **No security-reviewer** —
  parameterized SQL, no auth/PII/user-input, internal-dev provider.
- A `ShareholdingUpdated` event is a one-line add when an ownership-factor consumer subscribes (Epic 4).

### File List

**New**
- `backend/tests/integration/test_shareholding_ingest.py` — PIT-by-date upsert pipeline over real Postgres.

**Modified**
- `backend/src/quantvista/market_data/repositories.py` — `upsert_shareholding`.
- `backend/src/quantvista/market_data/services.py` — `ShareholdingIngestionService` + `ShareholdingReport`.
- `backend/src/quantvista/jobs/ingest.py` — `ingest_shareholding` task + `_run_shareholding` + `SHP_JOB_NAME`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-023 status; QV-022 → done (housekeeping).

### Change Log

- **2026-07-04 — QV-023 schema + ingest_shareholding (PIT ownership).** Verified the pre-existing `0005`
  `shareholding` schema conforms to `03` §4.1 (no migration change) and shipped the PIT-by-date upsert
  (`upsert_shareholding`, keyed `(stock_id, as_of_date)`), the provider-agnostic
  `ShareholdingIngestionService` (no event, per the `06` catalog), and the strict `ingest_shareholding`
  task. Upsert idempotency + new-quarter rows + isolation proven against real Postgres. 229 tests green,
  coverage 96 % (service 100 %); ruff/mypy-strict/import-linter clean. No migration.

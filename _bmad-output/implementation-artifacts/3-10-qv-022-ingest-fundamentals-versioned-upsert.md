---
baseline_commit: 884bca8f738f2997d3904d45e6471a7f82fec7ae
---

# Story 3.10: QV-022 — ingest_fundamentals (versioned upsert)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **fundamentals ingested through the bitemporal write primitive, with correction handling**,
so that **restatements are captured truthfully as new versions (never overwrites), re-runs are idempotent, and late corrections are ready to trigger re-scoring**.

> Canonical ID **QV-022** · Epic 3 (EPIC-DATA) · `[DATA]` · 5pts · Sprint 02 · depends: **QV-021 ✅** (bitemporal repo), **QV-012 ✅** (provider seam)
> Authoritative: `plans/06` §2 (job `ingest_fundamentals`, key `fund:{stock}:{period}:{rev}`, emits `FundamentalsUpdated`) · `06` §5 ("a fundamentals revision inserts a new bitemporal version and enqueues `compute_factors`/`compute_scores` for affected dates → scores self-heal") · `03` §5 (bitemporal correctness). The bitemporal versioning + idempotency is **already built + tested in QV-021** — this story is the ingestion wiring on top.

## Locked decisions

- **Wire the QV-021 primitive — do not re-implement versioning.** The service maps each `FundamentalSnapshot` → `record_fundamental_version(...)` per filing; the `inserted`/`revised`/`unchanged` semantics, the close-prior-insert-new transaction, the single-open invariant, and idempotency are QV-021's, already proven. QV-022 adds only: universe iteration, DTO→ratios mapping, per-stock isolation, the job wrapper, and the `FundamentalsUpdated` event.
- **Ingest only snapshots with a `period_end` (real filings); skip `period_end=None`.** `fundamentals.period_end` is `NOT NULL` and part of `uq_fundamentals_open` — a filing must have a period. The dev adapter returns only a `ttm` snapshot with `period_end=None` (a rolling metric, not a filing), so it is **skipped** (counted as no-data). This mirrors the universe-sync posture: the dev provider is a non-authoritative stub, the **mechanism is the deliverable** (fake-tested with quarterly filings), and real quarterly/annual filings with `period_end` arrive with the licensed vendor (**QV-072**). A live dev smoke therefore ingests **0** filings — honest, not a bug.
- **Batch run_key `fund:{market}:{date}` (job-level), per-filing idempotency in the primitive.** Consistent with `ingest_daily_prices`/`ingest_corporate_actions`. `06`'s `fund:{stock}:{period}:{rev}` is the *data* idempotency, which `record_fundamental_version` enforces (same period+values → `unchanged`; changed → new version = the `{rev}` bump). A restatement arriving on a **later** poll date → different run_key → the primitive sees changed values → `revised`.
- **Provider-agnostic + strict per-stock isolation.** Same shape as `PriceIngestionService`/`CorporateActionIngestionService`: injected provider/bus/mapper, imports no yfinance; one stock's failure never sinks the run (no-data ≠ error; unexpected error → failure → the job raises → retry). One knowledge instant per run (all filings share `knowledge_time = now()`).
- **`FundamentalsUpdated` via the injected `IEventBus`** (`LoggingEventBus` default). The real consumer that enqueues re-scoring is **QV-024** (event bus) / Epic 4 (`compute_*`) — noted, not wired here.

## Acceptance Criteria

1. **Ingest filings through the primitive.** A provider-agnostic `FundamentalsIngestionService(provider, event_bus, *, symbol_mapper)` pulls `provider.get_fundamentals(symbol)` for the active universe (open constituents, reusing `active_universe` + `SymbolMapper`), maps each `FundamentalSnapshot` with a **non-null `period_end`** to `record_fundamental_version(stock_id, period_end, statement_type, ratios={pe, forward_pe, pb, roe, roce, debt_equity})` (absent measures stay NULL), sharing one `knowledge_time` per run. Snapshots with `period_end=None` are skipped.
2. **Correction handling = bitemporal versions.** A first filing → `inserted`; a re-poll with identical values → `unchanged` (no new row); a re-poll with changed values (restatement) → `revised` (prior open version closed with `knowledge_to`, new open inserted; exactly one open — `uq_fundamentals_open` holds). All via QV-021's primitive; nothing destructively updated.
3. **Idempotent run.** Re-running the service/task over unchanged provider data creates **no** new versions (every filing → `unchanged`). Aggregate report tallies `filings_inserted`, `filings_revised`, `filings_unchanged`, `stocks_ok`, `stocks_no_data`, `stocks_failed`, `failures`.
4. **Run under the job framework, strict.** A Celery task `ingest_fundamentals(market="NSE", date_iso=None)` wrapped by `run_job` (`run_key = fund:{market}:{date}`, QV-015; recorded in `jobs_runs`), reusing the strict per-stock isolation (any unexpected failure → run `failed` → retry). Default poll date = `last_completed_session(today)`. Emits **`FundamentalsUpdated`**.
5. **Boundaries.** The service imports no yfinance/pandas; `market_data` stays a DAG leaf; `fundamentals`/`stocks`/`index_constituents` are global → privileged engine. No new dependency, **no migration**.
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on new code. **Integration** (real Postgres, fake provider/bus, seeded throwaway universe, cleanup): insert → `FundamentalsUpdated` + `as_of` sees it; idempotent re-run (all `unchanged`, row count unchanged); changed values → `revised`; a `period_end=None` snapshot is skipped (no row); per-stock isolation (one provider raises → `stocks_failed=1`, others ingested); the task path via `run_job` (`jobs_runs` recorded; strict-fail → run `failed`).

## Tasks / Subtasks

- [x] **Task 1 — FundamentalsIngestionService** (AC: #1, #2, #3, #5)
  - [x] `market_data/services.py` (extend): `FundamentalsReport` frozen dataclass + `FundamentalsIngestionService(provider, event_bus, *, symbol_mapper=_identity_mapper)`; `ingest(market, *, index_code="NIFTY200", knowledge_time=None) -> FundamentalsReport`. `active_universe` → per stock (isolated): `get_fundamentals` → for each snapshot with `period_end is not None`, build `ratios` from the 6 DTO measures and call `record_fundamental_version`; tally by action. Skip `period_end=None`. `ok` = stock yielded ≥1 filing; `no_data` = none; `failed` = exception. Emit `FundamentalsUpdated`.
- [x] **Task 2 — Celery task** (AC: #4)
  - [x] `jobs/ingest.py` (extend): `FUND_JOB_NAME`; `_run_fundamentals(market, key, index_code)` wrapping `FundamentalsIngestionService(YFinanceDevProvider(), LoggingEventBus(), symbol_mapper=yahoo_symbol).ingest(...)` in `run_job`, strict-raise on `stocks_failed` (reuse `IngestRunFailed`). `ingest_fundamentals(market="NSE", date_iso=None)` task (`run_key fund:{market}:{date}`, default `last_completed_session`). No beat entry (→ PV-005 cadence).
- [x] **Task 3 — integration tests + gates + reconcile** (AC: #6)
  - [x] `tests/integration/test_fundamentals_ingest.py`: fake provider/bus, seeded throwaway universe (unique `index_code`) + stocks, cleanup by ids/run_key. Cover insert+event+`as_of`; idempotent re-run; revised on change; `period_end=None` skipped; per-stock isolation; the task via `run_job` (success + strict-fail → `jobs_runs.status=failed`). Run all gates; reconcile QV-021 → done (already applied on this branch).

## Dev Notes

### Scope discipline
QV-022 = the **ingestion wiring** for fundamentals over the QV-021 bitemporal primitive: universe → provider → map → `record_fundamental_version` → event, idempotent + strict, under `run_job`. **Not this story:** the versioning/`as_of` logic (→ QV-021, done), `shareholding` ingest (→ QV-023), the real event consumer that enqueues re-scoring on a correction (→ QV-024 event bus + Epic 4 `compute_*`; QV-027 proves the self-heal end-to-end), the licensed vendor supplying real filings (→ QV-072), scheduling on beat (→ PV-005). **No migration.**

### Reuse map (this is mostly wiring)
- `record_fundamental_version(session, stock_id, period_end, statement_type, ratios, *, reported_at=None, knowledge_time=None) -> "inserted"|"revised"|"unchanged"` and `fundamentals_as_of(...)` — `market_data/fundamentals.py` (QV-021). The service opens **one** `privileged_session_scope` per stock (or per run) and calls the primitive; the primitive does the close-prior/insert-new.
- `active_universe`, `SymbolMapper`/`_identity_mapper`, `IngestReport`-style report shape, per-stock isolation loop — copy from `CorporateActionIngestionService` in `services.py`.
- `run_job`, `run_key`, `JobResult`, `IngestRunFailed`, `@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)`, `YFinanceDevProvider`, `yahoo_symbol`, `LoggingEventBus`, `last_completed_session` — mirror `ingest_corporate_actions` in `jobs/ingest.py`.
- Integration scaffold (seed throwaway market/stocks/constituents under a unique `index_code`, fake provider/bus, cleanup) — copy from `tests/integration/test_corporate_actions.py`.

### DTO → ratios mapping
`FundamentalSnapshot` (QV-012) carries: `symbol, period_end, statement_type, pe, forward_pe, pb, roe, roce, debt_equity, provenance`. Map `ratios = {"pe": s.pe, "forward_pe": s.forward_pe, "pb": s.pb, "roe": s.roe, "roce": s.roce, "debt_equity": s.debt_equity}` (all keys in the QV-021 allowlist; `None` values are fine → NULL). The other ~15 allowlist columns aren't supplied by this DTO and stay NULL; the primitive's `unchanged` check compares the full allowlist (unset both sides = NULL == NULL). `statement_type = s.statement_type or "quarterly"`; `reported_at = None` (DTO has none).

### The `period_end=None` skip (Locked decision)
The dev adapter's `get_fundamentals` returns one `ttm` snapshot with `period_end=None` (from Yahoo `info`), which is **not a filing** and can't satisfy `period_end NOT NULL` / `uq_fundamentals_open`. Skip it (no-data). Fake provider supplies quarterly snapshots **with** `period_end` to exercise the versioning. Real filings arrive with the licensed vendor (QV-072). A live dev smoke ingests 0 — expected.

### Boundaries & gates
- Service in `market_data/services.py` imports `fundamentals` (same context) + `core`; no yfinance/pandas; `market_data` stays a DAG leaf (`lint-imports` 3/3). `jobs/ingest.py` (composition root) already has the untyped-decorator mypy override — the new task is covered.
- Coverage ≥ 80% on the new service + task path. Ratios stay `Decimal`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (109 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf; service imports no yfinance) ·
  `pytest` → **221 passed, 3 skipped** (promtool, QV-020), coverage **96 %** — `services.py` **100 %**,
  `jobs/ingest.py` 90 % (the 3 uncovered lines are the daily-task body that resolves
  `last_completed_session(today)` + hard-codes NIFTY200 — exercised via `_run_fundamentals` in tests,
  same pattern as the price/corp-action daily tasks).
- **RED confirmed** first: `test_fundamentals_ingest.py` failed with
  `ImportError: cannot import name 'ingest_fundamentals' from quantvista.jobs.ingest`.

### Completion Notes List

- **Pure wiring over the QV-021 primitive.** `FundamentalsIngestionService` iterates the active
  universe, pulls `get_fundamentals`, and maps each `FundamentalSnapshot` (with a non-null `period_end`)
  → `record_fundamental_version(ratios={pe,forward_pe,pb,roe,roce,debt_equity})` sharing one
  `knowledge_time`. The versioning (inserted/revised/unchanged, close-prior/insert-new, single-open
  invariant, idempotency) is all QV-021's — proven again here end-to-end. **No migration.**
- **Correction handling verified:** first poll → `inserted`; identical re-poll → `unchanged` (no new
  row); a restatement (changed `pe`) on a later knowledge instant → `revised` (2 rows: old closed w/
  `knowledge_to`, new open) and `as_of` reads the restated value. Idempotent re-run creates no versions.
- **`period_end=None` skipped** (Locked decision): the dev adapter yields only a `ttm` snapshot with no
  period (a rolling metric, not a filing) → counted as no-data, no row written. A live dev smoke ingests
  0 filings — honest; real quarterly/annual filings arrive with the licensed vendor (QV-072). Verified.
- **Strict per-stock isolation + `run_job`:** one stock's provider error → `stocks_failed`, others still
  ingest; the task raises `IngestRunFailed` on any failure → `jobs_runs.status=failed` (tested both the
  success + strict-fail paths via `_run_fundamentals`). `run_key = fund:{market}:{date}`, not on beat
  (→ PV-005). Emits `FundamentalsUpdated`. **No security-reviewer** — parameterized SQL, no
  auth/PII/user-input, internal-dev provider.
- **Seam for QV-024/Epic 4:** `FundamentalsUpdated` is the hook a real event consumer subscribes to to
  enqueue `compute_factors`/`compute_scores` for affected dates (self-heal on corrections — QV-027).

### File List

**New**
- `backend/tests/integration/test_fundamentals_ingest.py` — versioned-upsert pipeline over real Postgres.

**Modified**
- `backend/src/quantvista/market_data/services.py` — `FundamentalsIngestionService` + `FundamentalsReport`.
- `backend/src/quantvista/jobs/ingest.py` — `ingest_fundamentals` task + `_run_fundamentals` + `FUND_JOB_NAME`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-022 status; QV-021 → done (housekeeping).

### Change Log

- **2026-07-04 — QV-022 ingest_fundamentals (versioned upsert).** Wired the QV-021 bitemporal primitive
  into a provider-agnostic ingestion service + `run_job` task: universe → `get_fundamentals` →
  `record_fundamental_version` per filing (inserted/revised/unchanged), `period_end=None` skipped, strict
  per-stock isolation, `FundamentalsUpdated` emitted. Correction handling + idempotency proven against real
  Postgres. 221 tests green, coverage 96 % (service 100 %); ruff/mypy-strict/import-linter clean. No migration.

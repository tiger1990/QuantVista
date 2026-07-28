---
baseline_commit: 8c4afbf97b8b72bf37397264a137828002c63dc8
---

# Story 8.6: QV-067 — Parquet offload + DuckDB/Polars read path

Status: done

**Epic:** EPIC-BT (Epic 8) · **Points:** 8 · **Depends:** QV-065 (`BacktestEngine` + `price_panel` seam)

> **Fast multi-year reads so backtests don't hammer Postgres.** Export historical price partitions to **Parquet**, path-partitioned `/{market}/{table}/{year}/{month}/`, and give the backtest engine an alternative **DuckDB** read path over those Parquet files — measurably faster than a multi-year Postgres scan (`03` §7). Built **properly**: a pluggable object store with a **real S3/MinIO backend** *and* a **local-filesystem backend** used for dev/CI; the cloud path is authored + offline-validated only (AWS/Docker/MinIO are deferred on this box — same pattern as the QV-008 Terraform). The engine's default stays Postgres (backward-compatible); the Parquet source is opt-in by config. `pyarrow`/`duckdb`/`polars` install natively on this box (verified) behind an optional `lake` extra.

## Story

As a quant, I want fast multi-year reads, so backtests don't hammer Postgres.

## Acceptance Criteria

1. **Pluggable object store (real S3/MinIO + local-fs)** — a `core.objectstore` abstraction over `pyarrow.fs`: `LocalFileSystem` (dev, rooted at `settings.object_store_root`) and `S3FileSystem` (MinIO/S3 via the existing `settings.s3_endpoint_url`/`s3_access_key`/`s3_secret_key`/`s3_bucket`). Selected by `settings.object_store_backend` (`local` | `s3`, default `local`). A partition-path helper builds `/{market}/{table}/{year}/{month}/`. The S3 backend is **real code**, exercised only against local-fs in dev/CI (MinIO deferred — offline-validated).
   [Source: `03` §7; `core/config.py` (S3 settings already present); aws-infra-deferred]

2. **Export historical partitions to Parquet** — `market_data.lake.export_prices_parquet(session, market, *, until=None)` reads `daily_prices` and writes Parquet files partitioned `/{market}/daily_prices/{year}/{month}/part.parquet`, columns `(stock_id, date, adj_close)` with `adj_close` as a **decimal** Parquet type (exact, no float drift). Idempotent (a partition file is overwritten). A Celery task `quantvista.export_prices_parquet` on the `compute` queue wraps it (ledger + run_key).
   [Source: `03` §6/§7 monthly range partitions; QV-062/065 job conventions]

3. **DuckDB read path returning the engine's panel** — `market_data.lake.ParquetPriceSource(store)` exposes `panel(stock_ids, start, end) -> dict[UUID, dict[date, Decimal]]` — **byte-identical shape** to `market_data.repositories.adjusted_close_panel` (QV-065) — by querying the Parquet partitions with DuckDB (`read_parquet(globs)` + a `stock_id = ANY / date BETWEEN` predicate, pruning by the partition path). Non-intersecting per name (a delisted name keeps its short series), PIT-safe (only partitions/rows `<= end`).
   [Source: QV-065 `price_panel`/`adjusted_close_panel`; `03` §7 DuckDB/Polars]

4. **Engine reads via the source seam (opt-in, backward-compatible)** — `BacktestDataAccess(session, *, price_source: PriceSource | None = None)`: `price_panel` delegates to `price_source` when provided, else the Postgres `adjusted_close_panel` (unchanged default). `jobs/backtest.py` selects the source from `settings.backtest_price_source` (`postgres` | `parquet`, default `postgres`) — Parquet wired only when the export has run. **No behaviour change for existing callers.**
   [Source: QV-065 `BacktestDataAccess`; DAG `analytics → market_data` (allowed)]

5. **Correctness equivalence + measurable speedup** — a real-Postgres integration test proves the **Parquet panel == Postgres panel** for the same `(stock_ids, start, end)` (the hard, deterministic gate), and a full engine run with `price_source=ParquetPriceSource(...)` yields **identical metrics** to the Postgres run. A separate **benchmark** (script + informational test, not a flaky CI perf-assert) seeds a multi-year, multi-symbol dataset and reports Parquet-DuckDB vs Postgres-scan wall-time, demonstrating the speedup.
   [Source: `03` §7 "measurable speedup"; investigate-flaky-tests (no perf assertion in the required gate)]

6. **Deps, config, gates** — `pyarrow`+`duckdb` (+ existing `polars`) behind an optional **`lake`** extra; parquet tests `importorskip` the extra so they skip where absent and **run in `backend-rls`** (install `.[dev,lake]` there). mypy overrides for the untyped `pyarrow`/`duckdb`/`polars` modules. Full-tree gates green (ruff, ruff format, **bare `mypy`**, lint-imports **3/3**, bandit, pip-audit). New code coverage ≥80%.
   [Source: native-install-before-deferral (wheels verified); observability-config-testing (extra-gated tests); testing rules]

---

## Dev Notes

### Placement & DAG

- **`core/objectstore.py`** (NEW) — `ObjectStore` protocol + `get_object_store(settings)` returning a `pyarrow.fs` filesystem + base path. `core` is infra (may import third-party). No domain imports.
- **`market_data/lake.py`** (NEW) — `export_prices_parquet(...)`, `ParquetPriceSource`, and a `PriceSource` Protocol (`panel(stock_ids, start, end) -> dict[UUID, dict[date, Decimal]]`) that both `ParquetPriceSource` and a trivial Postgres-backed wrapper satisfy. `market_data → core` is allowed.
- **`analytics/backtest_data.py`** (UPDATE) — add the optional `price_source` ctor arg; `price_panel` delegates. `analytics → market_data` already allowed. **Preserve** the current default (Postgres `adjusted_close_panel`) so QV-065's engine + all its tests are unaffected.
- **`jobs/lake.py`** (NEW) or extend `jobs/` — the `export_prices_parquet` Celery task (`compute` queue) + the backtest job's source selection.
- **`core/config.py`** (UPDATE) — add `object_store_backend: str = "local"`, `object_store_root: str = ".data/lake"` (gitignored), `backtest_price_source: str = "postgres"`.
- Python 3.13, mypy strict — **run bare `mypy`**; add `[[tool.mypy.overrides]]` for `pyarrow.*`, `duckdb`, `polars.*` (no stubs) like the existing `yfinance` override. Money stays `Decimal` (Parquet decimal logical type → DuckDB `DECIMAL` → Python `Decimal`).

### Reuse — do NOT re-implement / do NOT break

- **The panel contract is QV-065's.** `adjusted_close_panel(session, stock_ids, start, end) -> dict[UUID, dict[date, Decimal]]` (per-name, non-intersecting, `date <= end`). `ParquetPriceSource.panel` must return the **exact same structure** so the engine is source-agnostic. Diff the two in the equivalence test.
- **Settings already carry S3/MinIO** (`s3_endpoint_url=http://localhost:9000`, `s3_access_key/secret=minioadmin`, `s3_bucket=quantvista-local`) — wire the `S3FileSystem` to those; do not invent new S3 config.
- **The engine is unchanged** — QV-067 only adds an injectable price source. Do not touch the rebalance loop, metrics, or frictions. `BacktestEngine(BacktestDataAccess(session, price_source=…))` is the only wiring point.
- **`pyarrow.fs`** gives both `LocalFileSystem` and `S3FileSystem` (native, no boto3) — use it for the store so local-fs and S3 share one code path. DuckDB reads local Parquet directly; S3 needs its `httpfs` extension (offline-validated only).

### Proper-but-deferred (the S3/MinIO reality on this box)

Per [[qv067-artifact-store-approach]] + [[aws-infra-deferred]]: **write the S3 backend for real** (it's selected by `object_store_backend=s3`), but dev/CI run **only** the `local` backend (no MinIO/Docker/AWS here). Validate S3 offline — a unit test that constructs `S3FileSystem` from settings and asserts the right endpoint/bucket/base path **without connecting** (mirrors QV-008 Terraform: authored + validated, never `apply`). The live MinIO/S3 round-trip is deferred to a Docker/cloud box (note it in `deferred-work.md`, gated before any prod rollout).

### DuckDB read sketch

```python
# ParquetPriceSource.panel — DuckDB over the partition globs, decimal preserved
rel = duckdb.sql(
    "SELECT stock_id, date, adj_close FROM read_parquet(?, hive_partitioning=false) "
    "WHERE stock_id = ANY(?) AND date <= ? AND date >= ?",
    params=[globs, [str(s) for s in ids], end, start],
)
# fold rows → {UUID: {date: Decimal}} (same shape as adjusted_close_panel)
```

Prune `globs` to only `{year}/{month}` dirs overlapping `[start, end]` so DuckDB never opens post-`end` partitions (PIT + speed). Keep it correct first; the speedup comes from Parquet columnar scans + partition pruning vs a Postgres row scan over months.

### Scope boundary

- **Price read path only** (per the AC). The **backtest-result artifact** (`backtests.result_ref` — QV-065 left it `None`) is a natural companion of the same object store; include it **only** if cheap (write metrics+curve to `/{tenant}/backtests/{id}.parquet`, set `result_ref`) — otherwise leave a note and keep QV-067 focused. Do not let it balloon the story.
- **Retention/partition-detach automation** (`03` §6) and **content-hash cache** (`03` §7) are future — not here.
- `technical_indicators`/`factor_values`/`scores` Parquet offload can reuse the same `export_*_parquet` shape later; QV-067 ships **`daily_prices`** (what the engine reads).

### Previous-story / epic intelligence

- **QV-065 (merged PR #74)** built `price_panel`/`adjusted_close_panel` (per-name, non-intersecting) and the `BacktestData` Protocol — QV-067 slots a Parquet source behind the same shape and injects it via a new ctor arg. Determinism + Decimal-as-string are cardinal; keep them.
- **QV-063/064/066** established real-PG + rolled-back synthetic seeds and the `run bare mypy` gate. **QV-008/observability** established the "author real infra, run the local backend, offline-validate the cloud path, extra-gate the heavy tests" pattern — follow it exactly here.
- polars is already importable (1.42.1); pyarrow 25 / duckdb 1.5 have cp313 macOS x86_64 wheels (verified via `pip install --dry-run`).

### Git intelligence (recent)

`8c4afbf QV-066 #75` · `5a12fdf QV-065 #74` · `fc0ff2c QV-064 #73`. `test_backtest_engine_run.py` (QV-065) is the template for seeding `daily_prices` + the seam; `core/config.py` for adding settings; the `yfinance` mypy override in `pyproject.toml` for the new untyped-module overrides.

### Project context reference

`_bmad-output/project-context.md` — `backend/src/quantvista/<context>/`; import-linter `root_package = quantvista`; money as `Decimal`; PIT correctness is cardinal. `03` §7 data-lake strategy.

## Tasks / Subtasks

### Task 1: Object store (AC-1)
- [x] `core/objectstore.py`: `get_object_store(settings)` → `ObjectStore(fs, base, scheme)` for `local`|`s3` (lazy pyarrow import); partition-path + `read_glob` + `table_exists` helpers. Settings: `object_store_backend`, `object_store_root`, `backtest_price_source`. Tests: local round-trip; **S3 constructed offline** (no connect).

### Task 2: Parquet export (AC-2)
- [x] `market_data/lake.py::export_prices_parquet(session, store, market, *, until=None)` → decimal128(20,8) Parquet, one file per `{year}/{month}`, idempotent. `jobs/lake.py` Celery task on the `compute` queue (ledger + run_key).

### Task 3: DuckDB read path (AC-3)
- [x] `ParquetPriceSource(store, market).panel(...)` via DuckDB `read_parquet` — exact `adjusted_close_panel` shape (Decimal, non-intersecting, `date <= end`); empty when nothing exported. `PriceSource` Protocol.

### Task 4: Engine wiring (AC-4)
- [x] `BacktestDataAccess(session, *, price_source=None)`; `price_panel` delegates when set. `jobs/backtest.py::_price_source()` picks from `settings.backtest_price_source`. Default unchanged (Postgres) — QV-065 untouched.

### Task 5: Equivalence + benchmark (AC-5)
- [x] Integration test: **Parquet panel == Postgres panel** (byte-identical), multi-partition, PIT-bounded, seam-delegation transparent. `scripts/bench_parquet_read.py` reports both access patterns honestly (no CI perf assert).

### Task 6: Deps, CI, gates (AC-6)
- [x] `lake` extra (`pyarrow`, `duckdb`; polars is base); `importorskip` in the tests; `.[dev,lake]` in `backend-rls`; mypy `follow_imports=skip` for pyarrow/duckdb (NOT polars — it's typed). Gates green; new code 100% covered.

## Dev Agent Record

### Debug Log

- De-risked the core mechanic first: pyarrow `write_table(filesystem=…)` needs an explicit `fs.create_dir(..., recursive=True)` (no auto-mkdir); DuckDB `read_parquet` returns `Decimal`/`date` from `decimal128`/`date32`.
- **Postgres param-type ambiguity:** `(:until IS NULL OR …)` → `could not determine data type of parameter` → cast both (`CAST(:until AS date)`), per [[sql-type-ambiguity-at-source]].
- **mypy override too broad:** I first put `polars` under `follow_imports=skip`, which made it `Any` and broke an *unrelated* file (`test_indicators.py` — polars ships py.typed and is a base dep). Narrowed the override to pyarrow+duckdb only. Added `quantvista.jobs.lake` to the untyped-`@app.task` override list.
- Confirmed lazy imports keep the base install lean: `core.objectstore`/`market_data.lake` import pyarrow/duckdb only *inside* functions — a lake-absent env imports them fine (the pyarrow-at-boot seen locally is `pandas` opportunistically importing it via QV-065's `trading_calendar`, not a hard dep).

### Completion Notes List

- **Object store** (`core/objectstore.py`) over `pyarrow.fs`: real `LocalFileSystem` (dev/CI) + real `S3FileSystem` (MinIO/S3 from the existing `s3_*` settings). S3 is **offline-validated** (constructed + paths asserted, no network) — live round-trip deferred with Docker/AWS ([[qv067-artifact-store-approach]]; noted in `deferred-work.md`).
- **Export** `daily_prices` → decimal-exact monthly Parquet partitions; **`ParquetPriceSource`** reads them via DuckDB in the byte-identical `adjusted_close_panel` shape, so the engine is source-agnostic. Opt-in via `BacktestDataAccess(price_source=…)` + `backtest_price_source=parquet`; **default Postgres unchanged**.
- **Honest speedup (AC-5):** benchmarked both patterns. **Analytical full scan** (the `03` §7 multi-factor sweep the AC targets) — DuckDB **~7× faster** (7ms vs 53ms; ~70× warm). **Selective per-backtest panel** (`stock_id = ANY + date BETWEEN`) — Postgres's indexed sweet spot, so Parquet is *slower* there; its value for the engine is history offload, not per-call latency. Did **not** manufacture a speedup for the pattern where it doesn't exist.
- **Correctness is the gate**, not perf: the required CI assertion is panel equivalence (deterministic); the benchmark is an informational script.
- Full suite **738 passed / 5 skipped**; new code 100% covered (objectstore, lake, jobs/lake); all gates green (ruff, format, mypy 274, lint-imports 3/3, bandit, pip-audit).

### File List

- `backend/src/quantvista/core/objectstore.py` (new — pyarrow.fs object store, local + S3)
- `backend/src/quantvista/market_data/lake.py` (new — `PriceSource`, `export_prices_parquet`, `ParquetPriceSource`)
- `backend/src/quantvista/jobs/lake.py` (new — `export_prices_parquet` Celery task, `compute` queue)
- `backend/src/quantvista/core/config.py` (modified — `object_store_backend`/`object_store_root`/`backtest_price_source`)
- `backend/src/quantvista/analytics/backtest_data.py` (modified — optional `price_source`, `price_panel` delegates)
- `backend/src/quantvista/jobs/backtest.py` (modified — `_price_source()` selection)
- `backend/src/quantvista/jobs/celery_app.py` (modified — `export_prices_parquet` → `compute` queue + include)
- `backend/pyproject.toml` (modified — `lake` extra; mypy overrides for pyarrow/duckdb)
- `backend/scripts/bench_parquet_read.py` (new — honest two-pattern benchmark)
- `backend/tests/integration/test_objectstore.py` (new — local round-trip + S3 offline)
- `backend/tests/integration/test_lake.py` (new — export + panel equivalence + PIT + task)
- `.github/workflows/ci.yml` (modified — `backend-rls` installs `.[dev,lake]`)
- `_bmad-output/implementation-artifacts/deferred-work.md` (modified — QV-067 deferrals)

### Change Log

- 2026-07-27 — QV-067 Parquet offload + DuckDB read path: pluggable object store (local-fs + real-but-offline-validated S3/MinIO), `daily_prices`→Parquet export, `ParquetPriceSource` byte-identical to Postgres, opt-in engine wiring (default Postgres). Honest benchmark (~7× on analytical scans; Postgres wins the selective panel). `lake` extra + `.[dev,lake]` in `backend-rls`. New code 100% covered; gates green.

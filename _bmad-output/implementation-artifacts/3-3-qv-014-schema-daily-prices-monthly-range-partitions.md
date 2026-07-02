---
baseline_commit: 795069a919ab190e6524c2414a928a0a9b5b2847
---

# Story 3.3: QV-014 — Schema: daily_prices (monthly range partitions)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **the `daily_prices` table verified — monthly range-partitioned on `date`, unique per `(stock_id, date)`, `NUMERIC` money — with its partition-routing behavior locked in by regression tests**,
so that **price history scales and stays correct, and the partitioning can't silently regress**.

> Canonical ID **QV-014** · Epic 3 (EPIC-DATA) · `[DATA]` · 5pts · Sprint 01 · depends: **QV-013** (done)
> Authoritative schema: `plans/03-data-architecture.md` §4.1 (`daily_prices`) + §9 (partitioning strategy). Global table (no `tenant_id`, no RLS). Partition helper: `create_month_partition()` from migration `0001`.

## ⚠️ Read this first — the DDL already exists (verify, do NOT re-create)

`daily_prices` was **already authored** in migration **`0004_prices_partitioned.py`** (upfront `0001→0013` baseline, applied through 0013). This is the **same situation as QV-013** — a **verify + reconcile** story, not a new migration.

- **DO NOT write a new `create_table` migration** — `daily_prices` (partitioned, `relkind='p'`) with partitions `daily_prices_2026_06`, `daily_prices_2026_07`, `daily_prices_default` already exist. A duplicate `CREATE TABLE` breaks the DB.
- **This story = verify + reconcile:** confirm `0004` conforms to §4.1/§9, then **add integration tests** that lock in the AC guarantees (RANGE partitioning + row routing, the `create_month_partition()` helper, `(stock_id, date)` uniqueness, `NUMERIC` money, global/no-RLS, QV-012 `PriceBar` DTO column coverage). No schema change expected. **Only if a genuine §4.1/§9 gap is found**, add a forward `0014_*` migration (expand-only, never edit `0004`) and document it.
- Tests are `@pytest.mark.integration` (need Postgres) and **auto-skip without a DB** — mirror `tests/integration/test_reference_schema.py` (QV-013). `daily_prices` is currently **empty** (ingestion is QV-016), so tests insert + roll back cleanly.

## Acceptance Criteria

1. **Conformance confirmed + documented.** Verify `0004_prices_partitioned.py` defines `daily_prices` per §4.1 — `id`/`stock_id` FK/`date`/`open`/`high`/`low`/`close`/`adj_close` (`NUMERIC`), `volume` (`bigint`), `source`, `ingested_at`; **`PARTITION BY RANGE (date)`**; PK `(id, date)`; UNIQUE `(stock_id, date)`; btree `(stock_id, date DESC)`; BRIN on `date`; a `DEFAULT` partition + current/next-month partitions — and record field/constraint conformance in the Dev Agent Record. **No duplicate migration.**
2. **Partitioning + routing — integration test:** `daily_prices` is a partitioned table (`pg_class.relkind = 'p'`, `PARTITION BY RANGE(date)`); a row whose `date` falls in an existing monthly partition routes there (assert via `tableoid::regclass`), and a row whose `date` has **no** monthly partition lands in **`daily_prices_default`**.
3. **`create_month_partition()` helper — integration test:** calling `create_month_partition('daily_prices', '<month_start>')` creates a `daily_prices_YYYY_MM` partition; a row for that month then routes to the **new named partition** (not `default`); the call is **idempotent** (`CREATE TABLE IF NOT EXISTS` — a second call is a no-op).
4. **Uniqueness — integration test:** UNIQUE `(stock_id, date)` rejects a duplicate `(stock_id, date)` insert (`IntegrityError`). Note the constraint includes the partition key (`date`), as required for a partitioned unique.
5. **`NUMERIC` money, not float — test/assert:** `open`/`high`/`low`/`close`/`adj_close` are `numeric` and `volume` is `bigint` (query `information_schema.columns`). Money is never `float` (project rule).
6. **Global / no-RLS — integration test:** `daily_prices` has no `tenant_id` column, `relrowsecurity = false`, and zero `pg_policies` rows (global domain, rule #1).
7. **DTO alignment — test/assert:** `daily_prices` columns cover the QV-012 `PriceBar` DTO fields that will persist here (QV-016): `date, open, high, low, close, adj_close, volume, source` (the DTO `symbol` maps via `stock_id` at ingestion). Lightweight column-presence assertion.
8. **Gates green:** new tests pass in CI's `backend-rls` job and locally; skip cleanly with no DB. `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` all green. Tests roll back (no residue; any partition created by the helper is dropped on rollback).

## Tasks / Subtasks

- [x] **Task 1 — Verify conformance to §4.1/§9** (AC: #1)
  - [x] Read `0004_prices_partitioned.py`, `03` §4.1 (`daily_prices`) + §9 (partitioning), and `create_month_partition()` in `0001`. Record a field/constraint/partition conformance note in the Dev Agent Record. Confirm **no** migration change needed; if a real gap exists, plan a forward `0014_*` (expand-only) and document why.
- [x] **Task 2 — Partitioning + routing tests** (AC: #2)
  - [x] `tests/integration/test_daily_prices_schema.py` (`@pytest.mark.integration`, `admin_engine`, rollback pattern from QV-013): assert `relkind='p'`; insert a row in an existing month → `tableoid` is that monthly partition; insert a row in an unpartitioned month → `tableoid` is `daily_prices_default`.
- [x] **Task 3 — create_month_partition helper test** (AC: #3)
  - [x] Call the helper for a fresh month; insert a row for it → routes to the new `daily_prices_YYYY_MM` (not default); second call is a no-op (idempotent). All inside the rolled-back transaction (partition dropped on rollback).
- [x] **Task 4 — Uniqueness + NUMERIC + global/no-RLS + DTO** (AC: #4, #5, #6, #7)
  - [x] Duplicate `(stock_id, date)` → `IntegrityError` (via SAVEPOINT). Assert money columns are `numeric` / `volume` `bigint`. Assert no `tenant_id`, `relrowsecurity=false`, zero policies. Assert column presence covering the `PriceBar` DTO fields.
- [x] **Task 5 — Gates + reconcile** (AC: #8)
  - [x] Run `ruff`/`ruff format`/`mypy`/`lint-imports`/`pytest` (integration + unit). Confirm integration tests skip without a DB, pass with one. Record commands/output. Reconcile the story; QV-013 → done reconcile rides on this branch (housekeeping).

## Dev Notes

### Scope discipline — verification story (same as QV-013)
The `daily_prices` **DDL already exists** (`0004`, applied). QV-014's value is **regression tests** pinning the partitioning/uniqueness/money/no-RLS guarantees + a documented conformance check — **not** new DDL. **Not this story:** price *ingestion* (→ QV-016 `ingest_daily_prices`), adjusted-close computation (→ QV-017), a future-month partition **maintenance job** (a scheduled `create_month_partition` call — job framework is QV-015, wiring later), `fundamentals`/`technical_indicators` (own stories). Do not touch `0004` (immutable history) — any real gap is a forward `0014_*`.

### What already exists / context to build on
- **`0004_prices_partitioned.py`** — `daily_prices` `PARTITION BY RANGE (date)`; `id bigint GENERATED ALWAYS AS IDENTITY`; PK `(id, date)`; UNIQUE `(stock_id, date)`; `numeric(18,4)` OHLC/adj_close; `volume bigint`; FK `stock_id → stocks`; `ix_daily_prices_stock_id_date` (btree `(stock_id, date DESC)`); `brin_daily_prices_date` (BRIN); `daily_prices_default` DEFAULT partition; current + next month via `create_month_partition()`. Live partitions today: `daily_prices_2026_06`, `daily_prices_2026_07`, `daily_prices_default`; table is empty.
- **`create_month_partition(parent text, month_start date)`** (migration `0001`) — `CREATE TABLE IF NOT EXISTS <parent>_YYYY_MM PARTITION OF <parent> FOR VALUES FROM (month_start) TO (month_start + 1 month)`. Idempotent. DDL is transactional in Postgres → a partition created inside a test transaction is dropped on rollback.
- **QV-013 test pattern** (`tests/integration/test_reference_schema.py`): `@pytest.mark.integration`; `admin_engine` (superuser, correct for global tables); a `conn` fixture that opens a transaction and always rolls back (no residue); constraint-violation checks via `conn.begin_nested()` (SAVEPOINT) so the outer txn stays usable; `sqlalchemy.text()`. CI's **`backend-rls`** job provides Postgres + migrations; conftest auto-skips integration when no DB is reachable. **Reuse this pattern directly.**
- **QV-012 `PriceBar` DTO** (`market_data/models.py`): `symbol, date, open, high, low, close, adj_close (Decimal|None), volume (int|None), provenance`. `daily_prices` is its persistence target (mapping is QV-016); `symbol` ↔ `stock_id` resolution happens at ingestion.
- **Routing check:** `SELECT tableoid::regclass FROM daily_prices WHERE ...` returns the concrete partition a row lives in — the clean way to assert routing.
- **Migration conventions** (rule #5): forward-only, expand/contract, hand-written DDL, naming (`ix_`/`brin_`/`uq_`), helpers from `0001`. `daily_prices`/`technical_indicators`/`factor_values`/`scores` are the monthly-partitioned tables (§9).

### Testing notes
- Insert a market + stock first (FK), or reuse a seeded stock; simplest is to insert a throwaway market+stock in the same rolled-back txn (mirror QV-013 `_new_market`/`_new_stock` helpers — consider a tiny shared helper, but a self-contained file is fine).
- Idempotency: assert a second `create_month_partition` call for the same month does not raise.
- Money type: `SELECT data_type FROM information_schema.columns WHERE table_name='daily_prices' AND column_name IN ('close','adj_close') → numeric`.
- Keep it AAA + behavior-named. These are the §9 partitioning correctness guarantees.

### Project Structure Notes
- **New:** `backend/tests/integration/test_daily_prices_schema.py`.
- **Modified:** none expected (verification only). **Only if a real §4.1/§9 gap is found:** a new `0014_*.py` (expand-only) — flag in Completion Notes.
- **Housekeeping on this branch:** `sprint-status.yaml` QV-013 → done.

### References
- [Source: plans/sprints/sprint-01-data-backbone-i.md#QV-014] — story + AC (daily_prices, monthly range partitions).
- [Source: plans/03-data-architecture.md#41-reference--market-global] — `daily_prices` field list + unique/indexes.
- [Source: plans/03-data-architecture.md#9] — partitioning strategy (monthly range on `date`; BRIN/btree indexes).
- [Source: backend/src/quantvista/db/migrations/versions/0004_prices_partitioned.py] — the live DDL to verify.
- [Source: backend/src/quantvista/db/migrations/versions/0001_extensions_and_helpers.py] — `create_month_partition()` helper.
- [Source: backend/tests/integration/test_reference_schema.py, backend/tests/conftest.py] — the integration test + `admin_engine` + rollback + skip pattern to reuse.
- [Source: backend/src/quantvista/market_data/models.py] — QV-012 `PriceBar` DTO for the column-coverage check.
- [Source: _bmad-output/project-context.md] — rule #1 (global vs tenant), rule #5 (migrations/partitioning/naming), Decimal/NUMERIC-not-float.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow)

### Debug Log References

- Verified against local **PostgreSQL 18.4**; `daily_prices` partitioned (`relkind='p'`), empty,
  partitions `daily_prices_2026_06/07/default`.
- `pytest tests/integration/test_daily_prices_schema.py` → **9 passed**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (80 files) ·
  `lint-imports` 3 kept/0 broken · full `pytest` → **131 passed** (9 new; prior 122 unaffected).
- Integration tests `@pytest.mark.integration` → run where Postgres is reachable (local + CI
  `backend-rls`), auto-skip in the DB-free unit job.

### Completion Notes List

- **Verification story — no DDL written.** `daily_prices` already lives in
  `0004_prices_partitioned.py` (upfront QV-004 baseline). Added the regression tests that pin its
  partitioning/uniqueness/money/no-RLS guarantees. **No new migration** — `0004` conforms to §4.1/§9.
- **§4.1/§9 conformance (AC #1):** `daily_prices` `PARTITION BY RANGE (date)`; `id bigint IDENTITY`;
  PK `(id, date)`; UNIQUE `(stock_id, date)`; `numeric(18,4)` OHLC/adj_close; `volume bigint`;
  `source`/`ingested_at`; FK `stock_id → stocks`; btree `ix_daily_prices_stock_id_date` + BRIN
  `brin_daily_prices_date`; `daily_prices_default` + monthly partitions via `create_month_partition()`. ✓
- **Guarantees pinned by tests:** partitioned-table check (`relkind='p'`); row routing to the correct
  monthly partition and to `default` when unpartitioned (asserted via `tableoid::regclass`);
  `create_month_partition()` creates + routes a new month and is idempotent; UNIQUE `(stock_id, date)`
  rejects dups; money columns `numeric`/`volume` `bigint`; global/no-RLS (no `tenant_id`,
  `relrowsecurity=false`, zero policies); column coverage vs the QV-012 `PriceBar` DTO.
- **Test hygiene:** reuses the QV-013 pattern — a `conn` fixture in a transaction that always rolls
  back (Postgres DDL is transactional, so a partition the helper creates is dropped on rollback → no
  residue); SAVEPOINT (`begin_nested`) for the uniqueness violation. `daily_prices` is empty so
  creating a historical-month partition inside the txn never conflicts with existing rows.
- **No security-reviewer pass:** admin-role schema assertions, no auth/PII/user-input surface.
- **Housekeeping bundled on this branch:** QV-013 reconciled `review → done`.

### File List

**New**
- `backend/tests/integration/test_daily_prices_schema.py` — 9 integration tests verifying `0004`.

**Housekeeping (bundled, per branch convention)**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-013 → done; QV-014 status.

### Change Log

- **2026-07-02 — QV-014 daily_prices schema (verify + reconcile).** No DDL change: the partitioned
  table already exists in `0004_prices_partitioned.py`. Added `test_daily_prices_schema.py` (9
  integration tests) locking in RANGE-partition routing, `create_month_partition()` behavior +
  idempotency, `(stock_id, date)` uniqueness, `NUMERIC` money, global/no-RLS, and QV-012 `PriceBar`
  DTO column coverage. Documented §4.1/§9 conformance. 131 tests green; ruff/mypy-strict/import-linter
  clean. Reconciled QV-013 → done.

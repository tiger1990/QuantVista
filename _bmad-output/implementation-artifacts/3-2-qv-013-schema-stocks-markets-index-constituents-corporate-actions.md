---
baseline_commit: e407974ab4c9d7eacff92eca4765b31ddfbd7c74
---

# Story 3.2: QV-013 — Schema: stocks, markets, index_constituents, corporate_actions

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **the reference/master schema (`markets`, `stocks`, `index_constituents`, `corporate_actions`) verified against `03` §4.1 and its correctness guarantees locked in by regression tests**,
so that **prices and analytics have trustworthy, survivorship-bias-free anchors — and the schema can't silently drift**.

> Canonical ID **QV-013** · Epic 3 (EPIC-DATA) · `[DATA]` · 5pts · Sprint 01 · depends: **QV-004** (done)
> Authoritative schema: `plans/03-data-architecture.md` §4.1 (field lists) + §5 (PIT/survivorship). These are **global** tables (no `tenant_id`, no RLS).

## ⚠️ Read this first — the DDL already exists (verify, do NOT re-create)

The tables this story names were **already authored** in migration **`0003_reference_market.py`** (part of the upfront `0001→0013` baseline written during QV-004), are **applied through 0013**, and were **seeded by QV-005** (markets + NIFTY200 constituents). `0003` already matches `03` §4.1.

- **DO NOT write a new `create_table` migration** — it would duplicate live tables (`markets`/`stocks`/`index_constituents`/`corporate_actions`/`macro_series` all exist) and break the DB. This is the primary failure mode to avoid.
- **This story = verify + reconcile:** confirm `0003` conforms to §4.1, then **add integration tests** that lock in the AC guarantees (survivorship-free `delisted_on`, PIT open-membership uniqueness, `corporate_actions` uniqueness, global/no-RLS, alignment with the QV-012 DTOs). No schema change is expected. **If — and only if — a genuine gap vs §4.1 is found**, add a **new forward migration `0014_*`** (expand-only, never edit `0003`); document the gap in Completion Notes.
- Tests are `@pytest.mark.integration` (need Postgres) and **auto-skip without a DB** — the DB-free unit suite stays green; they run in CI's `backend-rls` job and against the local Postgres 18.

## Acceptance Criteria

1. **Conformance confirmed + documented.** Verify `0003_reference_market.py` defines `markets`, `stocks` (incl. `isin` + `delisted_on`), `index_constituents` (PIT membership), `corporate_actions` — with the unique constraints/indexes from `03` §4.1 — and record the field-by-field conformance (and any deviation) in the Dev Agent Record. **No duplicate migration.**
2. **Survivorship-free `stocks` (`03` §5) — integration test:** `stocks.delisted_on` is nullable; a stock with `delisted_on` set + `is_active = false` **remains queryable** (a `SELECT` returns it) — delisted names are never removed. Also assert the unique `(market_id, symbol)` and the `isin` index exist.
3. **PIT `index_constituents` — integration test:** the partial unique index `uq_index_constituents_open` enforces **at most one open membership** (`effective_to IS NULL`) per `(index_code, stock_id)`: a *closed* historical row (`effective_to` set) **and** a new open row coexist, but a **second open row** for the same pair raises `IntegrityError`. Assert the `CHECK (effective_to IS NULL OR effective_to > effective_from)`.
4. **`corporate_actions` uniqueness — integration test:** unique `(stock_id, ex_date, action_type)` rejects a duplicate insert (`IntegrityError`); `details` defaults to `{}::jsonb`; the `action_type` CHECK rejects an unknown type.
5. **Global tables have no tenancy/RLS — integration test:** none of `markets`/`stocks`/`index_constituents`/`corporate_actions` has a `tenant_id` column, and each has `relrowsecurity = false` with **no RLS policies** (query `pg_class`/`pg_policies`). This is the structural counterpart to project rule #1 (these are the *global* domain).
6. **DTO alignment — test/assert:** the table columns cover the QV-012 DTO fields that will persist here (QV-016) — e.g. `corporate_actions(ex_date, action_type, ratio_or_amount, details, source)` ↔ `CorporateAction`; `stocks(symbol, isin, company_name, sector, is_active)` ↔ `UniverseEntry`. A lightweight assertion (column presence) is enough; note the intentional superset (`action_type` CHECK also allows `rights`/`merger` beyond the DTO enum).
7. **Gates green:** new tests pass in CI's `backend-rls` job and locally; skip cleanly with no DB. `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` all green. Tests clean up after themselves (rollback or delete inserted fixtures) — no residue in shared reference tables.

## Tasks / Subtasks

- [x] **Task 1 — Verify conformance to §4.1** (AC: #1)
  - [x] Read `0003_reference_market.py` and `03` §4.1; produce a field/constraint conformance note (tables, columns, uniques, indexes, checks) in the Dev Agent Record. Confirm **no** migration change is needed. If a real gap exists, plan a forward `0014_*` (expand-only) and document why.
- [x] **Task 2 — Survivorship + stocks tests** (AC: #2)
  - [x] `tests/integration/test_reference_schema.py` (`@pytest.mark.integration`, `admin_engine`): insert a market + a delisted stock (`delisted_on`, `is_active=false`); assert it is SELECT-able; assert unique `(market_id, symbol)` rejects a dup; assert `ix_stocks_isin` exists. Roll back / delete fixtures.
- [x] **Task 3 — PIT index_constituents tests** (AC: #3)
  - [x] Same file: closed row + open row coexist; a second open row for the same `(index_code, stock_id)` raises `IntegrityError`; the `effective_to > effective_from` CHECK rejects a bad row.
- [x] **Task 4 — corporate_actions tests** (AC: #4)
  - [x] Duplicate `(stock_id, ex_date, action_type)` → `IntegrityError`; `details` default `{}`; unknown `action_type` rejected by CHECK.
- [x] **Task 5 — Global/no-RLS + DTO alignment** (AC: #5, #6)
  - [x] Assert no `tenant_id` column + `relrowsecurity=false` + no `pg_policies` rows for the four tables. Assert column presence covering the QV-012 DTO fields.
- [x] **Task 6 — Gates + reconcile** (AC: #7)
  - [x] Run `ruff`/`ruff format`/`mypy`/`lint-imports`/`pytest` (integration + unit). Ensure integration tests skip without a DB and pass with one. Record commands/output. Reconcile the story; QV-012 → done reconcile + PV-ledger note already ride on this branch (housekeeping).

## Dev Notes

### Scope discipline — this is a verification story
The reference/master **DDL already exists** (`0003`, applied + seeded). QV-013's value is **regression tests** that pin the AC guarantees + a documented conformance check — **not** new DDL. **Not this story:** `daily_prices` (→ QV-014 / `0004` already exists too), `fundamentals` (→ QV-021 / `0005`), ingestion (QV-016), SQLAlchemy ORM models (repo uses hand-written DDL, `target_metadata = None`). Do not touch `0003` (immutable history) — any real gap is a forward `0014_*`.

### Why the DDL pre-exists
The `0001→0013` migration set was authored upfront during QV-004 ("PostgreSQL + Alembic + RLS scaffolding") — so most Epic-3 "schema" stories are already implemented and just need verification + reconcile. `0003_reference_market.py` (Create Date 2026-06-14) is exactly the QV-013 schema.

### What already exists / context to build on
- **`0003_reference_market.py`** — `markets`, `stocks` (`isin`, `delisted_on`, `market_cap_bucket` CHECK, unique `(market_id, symbol)`, `ix_stocks_isin`/`ix_stocks_sector`/partial `ix_stocks_is_active`, `updated_at` trigger), `index_constituents` (`ix_index_constituents_index_code_stock_id`, partial unique `uq_index_constituents_open`, `effective_to>effective_from` CHECK), `corporate_actions` (`action_type` CHECK incl. `rights`/`merger`, `details jsonb DEFAULT '{}'`, unique `(stock_id, ex_date, action_type)`, `ix_corporate_actions_stock_id_ex_date`), `macro_series`.
- **Test pattern** (`tests/integration/test_seed_reference.py`, `test_rls_isolation.py`, `conftest.py`): `@pytest.mark.integration`; `admin_engine` session fixture (superuser, bypasses RLS — correct for global tables); `pytest_collection_modifyitems` auto-skips integration when no DB is reachable; use `sqlalchemy.text()` raw SQL. CI's **`backend-rls`** job provisions Postgres + applies migrations, so these run there; locally they run against Postgres 18.
- **QV-012 DTOs** (`market_data/models.py`): `PriceBar`/`CorporateAction`/`FundamentalSnapshot`/`ShareholdingSnapshot`/`UniverseEntry` — the eventual persistence targets. QV-013 only checks column coverage; DTO→row mapping is QV-016.
- **Migration conventions** (project-context rule #5): forward-only, expand/contract, hand-written DDL, naming (`ix_`/`uq_`/`ck_`/`fk_`/`pk_`), helpers from `0001` (`set_updated_at()`, `app_current_tenant()`, `create_month_partition()`).

### Testing notes
- Use `admin_engine` + a transaction you roll back (or explicit `DELETE` of inserted fixtures) so shared reference tables keep no residue. To assert an `IntegrityError` cleaves the connection usable, do each violating insert in its own `SAVEPOINT`/nested transaction or a fresh connection.
- Foreign keys: `stocks.market_id → markets`, `index_constituents.stock_id → stocks`, `corporate_actions.stock_id → stocks` — insert parents first; clean up children first (or rely on rollback).
- `relrowsecurity`: `SELECT relrowsecurity FROM pg_class WHERE relname = 'stocks'` → false. Policies: `SELECT count(*) FROM pg_policies WHERE tablename = 'stocks'` → 0.
- AAA, behavior-named. These are the survivorship/PIT correctness guarantees `03` §5 calls mandatory.

### Project Structure Notes
- **New:** `backend/tests/integration/test_reference_schema.py`.
- **Modified:** none expected (verification only). **Only if a real §4.1 gap is found:** a new `backend/src/quantvista/db/migrations/versions/0014_*.py` (expand-only) — flag prominently in Completion Notes.
- **Housekeeping on this branch:** `sprint-status.yaml` QV-012 → done; `docs/pending-verifications.md` clarity note (carried).

### References
- [Source: plans/sprints/sprint-01-data-backbone-i.md#QV-013] — story + AC (schema for stocks/index_constituents/corporate_actions; global; `delisted_on` + PIT mandatory).
- [Source: plans/03-data-architecture.md#41-reference--market-global] — authoritative field lists + uniques/indexes.
- [Source: plans/03-data-architecture.md#5] — survivorship-bias-free (`delisted_on`) + PIT membership rationale.
- [Source: backend/src/quantvista/db/migrations/versions/0003_reference_market.py] — the live DDL to verify against.
- [Source: backend/tests/integration/test_seed_reference.py, backend/tests/conftest.py] — integration test + `admin_engine` + skip pattern.
- [Source: backend/src/quantvista/market_data/models.py] — QV-012 DTOs for the column-coverage check.
- [Source: _bmad-output/project-context.md] — rule #1 (global vs tenant data), rule #5 (migrations: forward-only/expand-contract/naming), Decimal-not-float.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow)

### Debug Log References

- Verified against local **PostgreSQL 18.4**; all four reference tables present.
- `pytest tests/integration/test_reference_schema.py` → **18 passed**.
- Final gates: `ruff check`/`ruff format --check` clean · `mypy` (strict) Success (79 files) ·
  `lint-imports` 3 kept/0 broken · full `pytest` → **122 passed** (18 new; prior 104 unaffected).
- Integration tests are `@pytest.mark.integration` → they run where Postgres is reachable
  (local + CI `backend-rls`) and auto-skip in the DB-free unit job.

### Completion Notes List

- **Verification story — no DDL written.** The reference/master schema already lives in
  `0003_reference_market.py` (authored with the QV-004 baseline, applied through 0013, seeded by
  QV-005). This story adds the regression tests that lock in its correctness guarantees. **No new
  migration was needed** — `0003` conforms to `03` §4.1 (see conformance below).
- **§4.1 conformance (AC #1):**
  - `markets` — id/code(UNIQUE)/name/country/currency/timezone/trading_calendar/is_active/created_at ✓
    (plan calls it `trading_calendar_ref`; column is `trading_calendar` — semantic match, benign name diff).
  - `stocks` — id/market_id FK/symbol/isin/company_name/sector/industry/market_cap_bucket(CHECK)/
    listed_on/`delisted_on`(nullable)/is_active/created_at/updated_at; UNIQUE `(market_id, symbol)`;
    `ix_stocks_isin` ✓ (plus sector/is_active indexes + `updated_at` trigger).
  - `index_constituents` — id/index_code/stock_id FK/effective_from/effective_to(NULL)/weight;
    partial UNIQUE `uq_index_constituents_open`; `effective_to > effective_from` CHECK ✓.
  - `corporate_actions` — id/stock_id FK/ex_date/action_type(CHECK)/ratio_or_amount/`details jsonb
    DEFAULT '{}'`/source/ingested_at; UNIQUE `(stock_id, ex_date, action_type)` ✓.
- **Guarantees pinned by tests:** survivorship-free (delisted rows stay queryable; `delisted_on`
  nullable), PIT membership (exactly one open row per index/stock; history coexists), corp-action
  uniqueness + `action_type` CHECK + `{}` default, and the **global/no-RLS** posture (no `tenant_id`,
  `relrowsecurity=false`, zero `pg_policies`) for all four tables. Column-coverage asserted against
  the QV-012 `CorporateAction`/`UniverseEntry` DTOs (persistence mapping is QV-016).
- **Test hygiene:** all writes run in a transaction that is rolled back (no residue in shared
  reference tables); constraint-violation checks use `SAVEPOINT` (`begin_nested`) so the outer
  transaction stays usable; unique test values (uuid-suffixed codes/symbols) avoid clashes with seed.
- **No security-reviewer pass:** admin-role schema assertions, no user input / auth / PII surface.
- **Housekeeping bundled on this branch:** QV-012 reconciled `review → done`; the "two kinds of
  deferral" PV-ledger note carried over.

### File List

**New**
- `backend/tests/integration/test_reference_schema.py` — 18 integration tests verifying `0003`.

**Housekeeping (bundled, per branch convention)**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-012 → done; epic-3 already in-progress; QV-013 status.
- `docs/pending-verifications.md` — "two kinds of deferral" clarity note.

### Change Log

- **2026-07-02 — QV-013 reference/master schema (verify + reconcile).** No DDL change: the schema
  already exists in `0003_reference_market.py`. Added `test_reference_schema.py` (18 integration
  tests) locking in survivorship-free `delisted_on`, PIT open-membership uniqueness, `corporate_actions`
  uniqueness + CHECK + jsonb default, global/no-RLS posture, and QV-012 DTO column coverage. Documented
  §4.1 conformance. 122 tests green; ruff/mypy-strict/import-linter clean. Reconciled QV-012 → done.

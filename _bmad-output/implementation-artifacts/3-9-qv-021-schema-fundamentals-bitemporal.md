---
baseline_commit: cc243febd5e49a9a4e0979371b75cb1b03213673
---

# Story 3.9: QV-021 — Schema: fundamentals (bitemporal)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the analytics layer**,
I want **point-in-time-correct fundamentals — a bitemporal `fundamentals` table plus an `as_of(date)` read and a revision-aware write primitive**,
so that **scores and backtests read exactly what was *known* on a given date, with zero look-ahead bias, and restatements are captured as new versions without ever destroying history**.

> Canonical ID **QV-021** · Epic 3 (EPIC-DATA) · `[DATA]` · 8pts · Sprint 02 · depends: **QV-013 ✅** (stocks FK)
> Authoritative: `plans/03` §5 ("Bitemporal fundamentals: `period_end` + `knowledge_from/knowledge_to`; a score for date `D` reads the row where `knowledge_from <= D < knowledge_to`; revisions insert a new version and close the prior `knowledge_to`; nothing destructively updated. As-of querying: repositories expose `as_of(date)`; scoring/backtest engines must use it.") · `03` §4.1 (`fundamentals` DDL) — **the credibility backbone**.

## ⚠️ Read this first — the DDL already exists (verify, do NOT re-create)

`fundamentals` is already defined in **`0005_fundamentals_pit.py`** (applied; `id, stock_id, period_end, statement_type` + ~21 `NUMERIC` ratios + `reported_at, knowledge_from, knowledge_to`, `CHECK (knowledge_to IS NULL OR knowledge_to > knowledge_from)`, `uq_fundamentals_open` = one open version per `(stock_id, period_end, statement_type)`, `ix_fundamentals_stock_period`). **No new migration.** `0005` also creates `shareholding` — that is **QV-023's** table, out of scope here. QV-021's *net code* is the repository (`as_of` read + bitemporal write primitive) + regression tests that pin the AC guarantees.

## Locked decisions

- **Verify-and-reconcile the schema; ship the repository.** Like QV-013/QV-014, the DDL is pre-existing and immutable history — QV-021 confirms `0005` conforms to `03` §5/§4.1 (documented in the Dev Agent Record) and does **not** duplicate or alter it (a genuine gap would be a forward `0014_*`, expand-only). The new, shippable code is the **bitemporal repository**.
- **Two time axes, one read: `as_of(knowledge_date)`.** `period_end` = valid-time (what period the data describes); `knowledge_from/knowledge_to` = knowledge-time (when we knew it). `fundamentals_as_of(stock_id, as_of, statement_type)` returns the version whose **knowledge interval contains `as_of`** (`knowledge_from <= as_of AND (knowledge_to IS NULL OR as_of < knowledge_to)`), taking the **latest `period_end`** then latest `knowledge_from` — i.e. the most recent fundamentals we *knew* on that date. This is the single primitive scoring/backtests call to avoid look-ahead (`03` §5).
- **Revisions never overwrite — the write primitive versions.** `record_fundamental_version(...)` closes the current open version (`knowledge_to = knowledge_time`) and inserts a new open one (`knowledge_from = knowledge_time`); on identical values it is a **no-op** (`skip_if_unchanged`, so re-runs don't churn versions). This is the primitive **QV-022** wires the provider through; QV-021 owns + tests the bitemporal correctness.
- **Global reference table → privileged engine.** `fundamentals` carries no `tenant_id`/RLS (global, like `daily_prices`); repository uses `privileged_session_scope`. Ratios stay `Decimal` (never float).
- **Column safety on the dynamic write.** The write primitive builds its column list from a fixed **allowlist** of the `NUMERIC` ratio columns (values always parametrised) — never from caller-supplied names — so a dict-driven insert can't inject SQL.

## Acceptance Criteria

1. **Schema conformance confirmed + documented.** Verify `0005` defines `fundamentals` with `period_end`, `statement_type`, `reported_at`, `knowledge_from`, `knowledge_to`, all ratios `NUMERIC` (never float), the `knowledge_to > knowledge_from` CHECK, `uq_fundamentals_open` (one open version per `(stock_id, period_end, statement_type)`), and `ix_fundamentals_stock_period`. Record the field/constraint conformance (+ any deviation) in the Dev Agent Record. **No duplicate migration.**
2. **Bitemporal versioned write.** `record_fundamental_version(session, stock_id, period_end, statement_type, ratios, *, reported_at=None, knowledge_time=None) -> Literal["inserted","revised","unchanged"]`: first version → `inserted`; a revision with changed values → closes the prior open version (`knowledge_to = knowledge_time`) and inserts a new open version → `revised`; identical values → `unchanged` (no write). Never updates ratio columns in place; `uq_fundamentals_open` is always satisfied (≤1 open version). `ratios` keys validated against the ratio-column allowlist.
3. **`as_of` read (no look-ahead).** `fundamentals_as_of(session, stock_id, as_of, *, statement_type="quarterly") -> FundamentalVersion | None` returns the version valid at knowledge-date `as_of` (interval contains `as_of`), newest `period_end` first. A date **before** the first `knowledge_from` returns `None`. After a revision, `as_of` at a date **between** the old and new `knowledge_from` returns the **old** version; at/after the new one returns the **new** version — proving point-in-time correctness.
4. **Boundaries + types.** Repository imports no yfinance/pandas; `market_data` stays a DAG leaf; global table → privileged engine; ratios `Decimal`. New module `market_data/fundamentals.py` (keeps `repositories.py` focused).
5. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on the new module. **Integration** (real Postgres, seeded throwaway stock, cleanup): first insert → `inserted` + one open row; identical re-run → `unchanged` (no new row); changed values → `revised` (prior closed with `knowledge_to`, new open, still exactly one open — `uq_fundamentals_open` holds); `as_of` PIT walk (before→None, between→old, after→new, latest-period selection); the `knowledge_to > knowledge_from` CHECK rejects an inverted interval; the ratio allowlist rejects an unknown column.

## Tasks / Subtasks

- [x] **Task 1 — verify schema conformance (§5/§4.1)** (AC: #1)
  - [x] Read `0005_fundamentals_pit.py` + `03` §5/§4.1; produce a field/constraint conformance note (columns, `NUMERIC` types, `uq_fundamentals_open`, CHECK, index) in the Dev Agent Record. Confirm **no** migration change needed; a real gap → plan a forward `0014_*` (expand-only) and document why.
- [x] **Task 2 — bitemporal repository: read + write** (AC: #2, #3, #4)
  - [x] `market_data/fundamentals.py`: `_RATIO_COLUMNS` allowlist (frozenset of the `NUMERIC` ratio names); frozen `FundamentalVersion` read model (id, stock_id, period_end, statement_type, reported_at, knowledge_from, knowledge_to, `ratios: dict[str, Decimal | None]`).
  - [x] `fundamentals_as_of(session, stock_id, as_of, *, statement_type="quarterly") -> FundamentalVersion | None` — interval-contains-`as_of`, `ORDER BY period_end DESC, knowledge_from DESC LIMIT 1`.
  - [x] `record_fundamental_version(session, stock_id, period_end, statement_type, ratios, *, reported_at=None, knowledge_time=None) -> str` — resolve `knowledge_time=now()` default; validate `ratios` keys ⊆ allowlist (else `ValueError`); read the open version; identical → `unchanged`; else close prior (if any) + insert new (dynamic column list from the allowlist, values parametrised); return `inserted`/`revised`.
- [x] **Task 3 — integration tests + gates** (AC: #5)
  - [x] `tests/integration/test_fundamentals.py`: seeded throwaway market+stock (unique), fake nothing (raw values), cleanup by stock_id. Cover insert/unchanged/revised + the single-open invariant; the `as_of` PIT walk (before/between/after + latest-period); the CHECK rejection; the allowlist rejection. Run all gates; reconcile QV-020 → done (already applied on this branch).

## Dev Notes

### Scope discipline
QV-021 = the **bitemporal fundamentals backbone**: verify the existing `0005` schema + ship the `as_of` read and the revision-aware write primitive, with PIT correctness proven by tests. **Not this story:** `ingest_fundamentals` wiring the provider (→ **QV-022**, which calls `record_fundamental_version` per filing), `shareholding` ingest (→ **QV-023**; its table also lives in `0005`), scoring/factor use of `as_of` (Epic 4), any ORM models (hand-written DDL; `target_metadata = None`). **No new migration** — do not touch `0005` (immutable history); a real gap is a forward `0014_*`.

### The bitemporal model (`03` §5)
```
period_end  = valid-time  (which fiscal period the numbers describe)
knowledge_* = knowledge-time (when WE knew them)

t0  file Q1 (period_end=Mar-31), knowledge_from=t0, knowledge_to=NULL   → open
t1  restate Q1                  close old (knowledge_to=t1); insert new knowledge_from=t1, knowledge_to=NULL

as_of(D):  the row with knowledge_from <= D < knowledge_to (NULL = open), newest period_end.
  D < t0 → None ;  t0 <= D < t1 → original ;  D >= t1 → restated.
```
`uq_fundamentals_open` (partial unique WHERE `knowledge_to IS NULL`) guarantees exactly one open version per `(stock, period, statement_type)`; the CHECK guarantees a well-formed interval. The repository must respect both (close-then-insert in one transaction).

### Schema facts — `fundamentals` (`0005`, read-only)
`id bigint PK`, `stock_id uuid FK stocks`, `period_end date NOT NULL`, `statement_type text CHECK in (quarterly|annual|ttm)`, ratios `numeric(18,6)` / money `numeric(20,2)` (pe, forward_pe, pb, roe, roce, roic, debt_equity, revenue, revenue_growth, eps, eps_growth, fcf, fcf_growth, operating_margin, net_margin, current_ratio, quick_ratio, ev_ebitda, peg, price_sales, enterprise_value), `reported_at timestamptz`, `knowledge_from timestamptz NOT NULL DEFAULT now()`, `knowledge_to timestamptz`, `source`, `ingested_at`. `uq_fundamentals_open (stock_id, period_end, statement_type) WHERE knowledge_to IS NULL`; `ix_fundamentals_stock_period (stock_id, period_end, knowledge_from DESC)`. Global (no RLS).

### Reuse map
- `privileged_session_scope` (`core/db.py`) — global-table access.
- The QV-012 DTO `FundamentalSnapshot` (symbol, period_end, statement_type, pe/forward_pe/pb/roe/roce/debt_equity, provenance) is what **QV-022** will map into `record_fundamental_version(ratios={...})` — QV-021 only needs the repository to accept the ratio dict (the dev provider fills a subset; absent columns stay NULL).
- Integration scaffold (seed throwaway market/stock, cleanup by id) — copy from `tests/integration/test_corporate_actions.py` / `test_universe_sync.py`.
- Hand-written DDL; migrations are SQL via alembic `op.execute` (`target_metadata = None`) — no ORM/autogenerate.

### Boundaries & gates
- `market_data/fundamentals.py` imports only `core`/stdlib/sqlalchemy; `market_data` stays a DAG leaf (`lint-imports` 3/3). Ratios `Decimal`. mypy `--strict`: annotate all; frozen `@dataclass(slots=True)`; `Literal["inserted","revised","unchanged"]` return.
- Coverage ≥ 80% on `fundamentals.py`. Dynamic INSERT column list comes from `_RATIO_COLUMNS` (fixed allowlist) with parametrised values — assert an unknown-key `ValueError` in tests.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (108 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf; `fundamentals.py` imports only core/stdlib/sqlalchemy) ·
  `pytest` → **213 passed, 3 skipped** (promtool, QV-020), coverage **96 %** — `market_data/fundamentals.py` **100 %**.
- **RED confirmed** first: `test_fundamentals.py` failed with `ModuleNotFoundError: quantvista.market_data.fundamentals`.

### Completion Notes List — Task 1 schema conformance (`0005` vs `03` §5/§4.1)

**`fundamentals` conforms — NO migration change.** Field/constraint verification:

| AC requirement (`03` §5/§4.1) | `0005_fundamentals_pit.py` | ✓ |
|---|---|---|
| `period_end` (valid-time) | `period_end date NOT NULL` | ✓ |
| `statement_type` | `text NOT NULL DEFAULT 'quarterly' CHECK in (quarterly/annual/ttm)` | ✓ |
| `reported_at` | `reported_at timestamptz` | ✓ |
| knowledge interval | `knowledge_from timestamptz NOT NULL DEFAULT now()`, `knowledge_to timestamptz` (NULL=open) | ✓ |
| ratios `NUMERIC` (never float) | 21 cols `numeric(18,6)` / money `numeric(20,2)` | ✓ |
| well-formed interval | `CHECK (knowledge_to IS NULL OR knowledge_to > knowledge_from)` | ✓ |
| one open version | `uq_fundamentals_open (stock_id, period_end, statement_type) WHERE knowledge_to IS NULL` | ✓ |
| as-of index | `ix_fundamentals_stock_period (stock_id, period_end, knowledge_from DESC)` | ✓ |
| global (no RLS) | no `ENABLE ROW LEVEL SECURITY` → privileged engine | ✓ |

No deviation; no forward `0014_*` needed. (`0005` also creates `shareholding` = QV-023's table — untouched here.)

### Completion Notes List — implementation

- **Ships the bitemporal repository** (`market_data/fundamentals.py`, 100 % cov): `fundamentals_as_of`
  (interval-contains-`as_of`, newest `period_end` first — the single no-look-ahead read) + the
  `record_fundamental_version` write primitive (`inserted`/`revised`/`unchanged`). A restatement
  **closes** the prior open version (`knowledge_to = knowledge_time`) and **inserts** a new open one in
  the same transaction — `uq_fundamentals_open` always holds; nothing is destructively updated.
- **PIT correctness proven** by the `as_of` walk: before first filing → `None`; between the two
  `knowledge_from`s → the **original** value; after the restatement → the **restated** value; newest
  `period_end` selected across periods.
- **Idempotency:** identical re-run → `unchanged` (no new version), so ingestion re-runs (QV-022) don't
  churn history. `Decimal` equality handles `10` vs the stored `10.000000` (value equality, not scale).
- **SQL-injection-safe dynamic insert:** the column list comes only from the `_RATIO_COLUMNS` allowlist
  (values parametrised); an unknown ratio key raises `ValueError` (tested). **No security-reviewer** beyond
  this — read/write of a global reference table, no auth/PII/user-input.
- **`as_of` takes a `datetime`** (knowledge instant) rather than a bare `date`, since `knowledge_from/to`
  are `timestamptz` — QV-022/scoring pass the intended instant. Not this story: `ingest_fundamentals`
  (→ QV-022, wires the provider through `record_fundamental_version`), `shareholding` (→ QV-023).

### File List

**New**
- `backend/src/quantvista/market_data/fundamentals.py` — bitemporal `as_of` read + `record_fundamental_version` write.
- `backend/tests/integration/test_fundamentals.py` — PIT correctness, versioning, invariants (real Postgres).

**Modified**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-021 status; QV-020 → done (housekeeping).

### Change Log

- **2026-07-04 — QV-021 bitemporal fundamentals.** Verified the pre-existing `0005` schema conforms to
  `03` §5/§4.1 (no migration change) and shipped `market_data/fundamentals.py`: the no-look-ahead `as_of`
  read + the revision-aware `record_fundamental_version` write primitive (close-prior + insert-new;
  identical → no-op; allowlist-guarded dynamic insert). PIT correctness + the single-open invariant +
  CHECK/allowlist rejections proven against real Postgres. 213 tests green, coverage 96 % (module 100 %);
  ruff/mypy-strict/import-linter clean. QV-022 wires the provider through this primitive.

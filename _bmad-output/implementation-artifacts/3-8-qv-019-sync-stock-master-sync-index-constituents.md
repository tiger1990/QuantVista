---
baseline_commit: 7b95cef70dfdc12e41dd5ec288d7a7959e3841a3
---

# Story 3.8: QV-019 — sync_stock_master + sync_index_constituents

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **the security master (`stocks`) and index membership (`index_constituents`) kept current through idempotent, point-in-time sync jobs**,
so that **the tradable universe stays correct over time — new listings appear, index reconstitutions open/close membership without destroying history, and every downstream job (ingest, indicators, factors, scores) reads a universe that reflects reality on any given date**.

> Canonical ID **QV-019** · Epic 3 (EPIC-DATA) · `[DATA]` · 3pts · Sprint 01 · depends: **QV-013 ✅** (schema), builds on QV-012 provider seam + QV-015 job framework
> Authoritative: `plans/06` §2 job catalog — `sync_stock_master` (`master:{market}:{week}`, emits `StockMasterUpdated`) + `sync_index_constituents` (`constituents:{index}:{date}`, emits `ConstituentsUpdated`) · `03` §5 (survivorship-free history; membership is **point-in-time**, revisions never overwrite).

## Locked decisions

- **Build the sync *mechanism*, verify with a fake provider — do NOT run `sync_index_constituents` against the dev stub.** Our only working provider is `YFinanceDevProvider`, whose `list_universe` is a **5-symbol, non-authoritative** dev list. QV-005 seeded **12** open NIFTY200 constituents. Running the reconstitution reconcile against the 5-symbol stub would PIT-**close** the other 7 seeded members — fabricated precision. So: the two jobs are built PIT-correct, provider-agnostic, and **weights-capable**, and are exercised end-to-end by a **fake provider** (add / drop / reconstitution / idempotent / weights). The **seeded 12 stay the dev universe**; the real NIFTY-200 + weights arrive with the **licensed vendor (QV-072)**, which will be the *only* authoritative membership source. Neither job is added to `beat_schedule` (dev has no authoritative feed → PV-005 cadence, consistent with QV-016/017/018). `sync_stock_master` is upsert-only (non-destructive) so it *may* run against dev safely, but is likewise unscheduled for now.
- **Reuse the existing `IMarketDataProvider.list_universe` seam — no new `IndexProvider` interface.** Universe listing already lives on the QV-012 provider seam with the `UniverseEntry` DTO (rule #8). Fake = tests, `YFinanceDevProvider` = non-authoritative dev convenience, licensed = future authoritative (QV-072). Authority is carried by `Provenance.license_class` (`non_commercial_dev` vs `commercial_licensed`). If a dedicated index vendor ever diverges from the price vendor, extract `IIndexProvider` **then** — YAGNI now.
- **`UniverseEntry` gains an optional `weight: Decimal | None = None`.** Additive, backward-compatible (existing QV-012 construction keeps working). The dev adapter supplies `None`; a licensed adapter (or the fake, in tests) supplies real index weights, which the constituents reconcile writes to the open membership row. `index_constituents.weight` already exists (`0003`).
- **`list_universe` returns the CANONICAL symbol, not the Yahoo ticker.** `UniverseEntry.symbol` is the platform identity that maps 1:1 to `stocks.symbol` (`RELIANCE`), with the venue in `UniverseEntry.exchange` (`NSE`). The dev adapter currently leaks `RELIANCE.NS` into `symbol`; QV-019 fixes it to strip its own suffix (the adapter owns its mapping). Any QV-012 test asserting the suffixed form is updated.
- **PIT reconcile is survivorship-free.** Adds insert a fresh open row (`effective_from = as_of`, `effective_to = NULL`); drops **close** the open row (`effective_to = as_of`) — never delete. Re-adding a previously-dropped stock inserts a new open row (the closed one stays as history; the `uq_index_constituents_open` unique index permits exactly one open row per `(index, stock)`). `as_of` must be **strictly after** an open row's `effective_from` to satisfy the `effective_to > effective_from` CHECK.
- **No new migration.** `stocks` + `index_constituents` exist (`0003`). Global tables → **privileged** engine.

## Acceptance Criteria

1. **`sync_stock_master` — upsert the security master from the provider.** Pulls `provider.list_universe(index_code)` and upserts each `UniverseEntry` into `stocks` keyed `(market_id, symbol)`: **insert** unseen securities (`symbol`, `company_name` from `name`, `isin`, `is_active`), **update** `company_name`/`isin`/`is_active`/`updated_at` on existing. **Never deletes / delists** based on universe membership (master is the security catalogue, not the index). Resolves `market_id` from `market` code. Emits **`StockMasterUpdated`**. Idempotent: a second run with the same provider data inserts 0, updates in place.
2. **`sync_index_constituents` — PIT reconcile of membership.** Pulls the provider's current set for `index_code`, resolves each to a `stock_id` via `(market, symbol)`, and reconciles against the **open** rows (`effective_to IS NULL`): **adds** (provider − open) → insert open row (`effective_from = as_of`, `weight = entry.weight`); **drops** (open − provider) → set `effective_to = as_of`; **unchanged** (∩) → refresh `weight` on the open row. Survivorship-free (no deletes). A provider symbol with no matching `stocks` row is **unresolved** → strict failure (master must run first). Emits **`ConstituentsUpdated`**. Idempotent: same set → 0 adds, 0 closes.
3. **Point-in-time correctness.** After a reconstitution (`as_of = D`), a dropped member's row has `effective_to = D` (still queryable for dates `< D`); a new member's row is open from `D`. `active_universe(index_code, market)` (QV-016 repo) reflects exactly the current provider set post-sync. The `effective_to > effective_from` CHECK is respected (guard `as_of > effective_from`).
4. **Provider-agnostic + weights-capable.** `UniverseSyncService(provider, event_bus)` imports **no** yfinance/pandas; provider + bus injected. `UniverseEntry.weight` (new, optional) is threaded from provider → open membership row. `market_data` stays a DAG leaf.
5. **Run under the job framework.** `jobs/universe.py`: `sync_stock_master(market="NSE", index_code="NIFTY200")` (`run_key = master:{market}:{iso-week}`) and `sync_index_constituents(index_code="NIFTY200", market="NSE", date_iso=None)` (`run_key = constituents:{index}:{date}`), each wrapped by `run_job` (QV-015; recorded in `jobs_runs`). Strict: an unresolved constituent raises → run `failed`. Default `as_of = last_completed_session(today)`. **Not** added to `beat_schedule` (→ PV-005 / licensed feed).
6. **Dev-adapter honesty.** `YFinanceDevProvider.list_universe` returns **canonical** symbols (strips its `.NS` suffix) with `license_class = non_commercial_dev`, and its docstring / `_DEV_UNIVERSE` comment state it is a **non-authoritative** dev convenience — the licensed adapter (QV-072) is the only authoritative NIFTY-200 source.
7. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on new code. **Unit:** the reconcile diff (adds/drops/unchanged) if any pure helper is extracted; the adapter canonical-symbol mapping. **Integration** (real Postgres, fake provider, seeded throwaway market/universe, cleanup): `sync_stock_master` inserts new + updates existing + is idempotent + emits `StockMasterUpdated`; `sync_index_constituents` opens adds, closes drops (PIT `effective_to` set, row retained), updates weights, is idempotent, resolves via `stocks`, raises on an unresolved symbol; a full **reconstitution scenario** (start {A,B,C} → sync {B,C,D}: A closed, D opened, B/C untouched) with `active_universe` reflecting {B,C,D}. Fake provider/bus (no network).

## Tasks / Subtasks

- [x] **Task 1 — seam: weight on `UniverseEntry` + canonical dev `list_universe`** (AC: #4, #6)
  - [x] `models.py`: add `weight: Decimal | None = None` (last field, default keeps QV-012 construction valid).
  - [x] `adapters/yfinance_dev.py`: `list_universe` returns canonical `symbol` (strip the `.NS`/`.BO` suffix it owns), `exchange="NSE"`, `weight=None`; docstring + `_DEV_UNIVERSE` comment mark it **non-authoritative dev-only**. Update any QV-012 test asserting the suffixed symbol.
- [x] **Task 2 — repository: master upsert + PIT constituents reconcile** (AC: #1, #2, #3)
  - [x] `repositories.py`: `upsert_stocks(session, market_code, entries) -> tuple[int, int]` (inserted, updated) — `INSERT … ON CONFLICT (market_id, symbol) DO UPDATE`, resolving `market_id` from `markets.code`. Never delists.
  - [x] `repositories.py`: `reconcile_constituents(session, index_code, market_code, members, as_of) -> ConstituentCounts` where `members` = `list[(symbol, weight)]`. Resolve `stock_id` per symbol (collect unresolved); compute open set; INSERT adds (open row + weight), UPDATE `effective_to = as_of` for drops (guarding `as_of > effective_from`), UPDATE weight for unchanged. Return counts (+ unresolved list). Set-based SQL where practical.
- [x] **Task 3 — UniverseSyncService** (AC: #1, #2, #4)
  - [x] `services.py`: `UniverseSyncService(provider, event_bus)`; `sync_stock_master(market, *, index_code="NIFTY200") -> StockMasterReport` (list_universe → upsert_stocks → emit `StockMasterUpdated`); `sync_index_constituents(index_code, market, as_of, *, ...) -> ConstituentsReport` (list_universe → reconcile_constituents → emit `ConstituentsUpdated`; unresolved → raise). Frozen report dataclasses. No yfinance import.
- [x] **Task 4 — Celery tasks** (AC: #5)
  - [x] `jobs/universe.py` (new): `sync_stock_master` task (`run_key master:{market}:{iso-week}`) + `sync_index_constituents` task (`run_key constituents:{index}:{date}`, default `as_of = last_completed_session`), each via `run_job`; strict raise on unresolved. Reuse `LoggingEventBus`, `yahoo_symbol` not needed (canonical). Not on beat. Add `quantvista.jobs.universe` to the mypy untyped-decorator override.
- [x] **Task 5 — tests + gates + reconcile** (AC: #7)
  - [x] `tests/integration/test_universe_sync.py`: fake provider/bus, seeded throwaway market + stocks + constituents (unique `index_code`), cleanup by ids/run_key. Cover master insert/update/idempotent/event; constituents add/close/weight/idempotent/unresolved-raise; full reconstitution → `active_universe` reflects the new set. Unit-test the adapter canonical mapping. Run all gates; reconcile QV-018 → done (housekeeping, already applied on this branch).

## Dev Notes

### Scope discipline
QV-019 = the **sync machinery** for master + membership: two idempotent, PIT-correct, provider-agnostic jobs behind the existing `list_universe` seam, verified with a fake provider. **Not this story:** populating the real NIFTY-200 or real weights (→ **QV-072** licensed vendor — the only authoritative source; dev stays the seeded 12), scheduling on beat (→ PV-005), fundamentals/shareholding sync (own stories), the real event-bus consumers of `StockMasterUpdated`/`ConstituentsUpdated` (→ QV-024), auto-delisting from `stocks`. **No new migration.**

### The provider seam (your architecture question, confirmed)
```
IMarketDataProvider.list_universe(index_code) -> Sequence[UniverseEntry]   (QV-012, rule #8)
   ├── _FakeProvider        ← deterministic tests (this story's verification)
   ├── YFinanceDevProvider  ← dev only; _DEV_UNIVERSE = NON-AUTHORITATIVE (license_class=non_commercial_dev)
   └── LicensedProvider     ← future (QV-072): the ONLY authoritative NIFTY-200 + weights (commercial_licensed)
```
No new interface — `UniverseEntry` already models a universe member; we add the optional `weight`.

### PIT reconcile — exact semantics (`03` §5)
- `P` = provider's current canonical symbols (+ weights). `O` = open rows (`effective_to IS NULL`) for `index_code`.
- **adds** = `P − O` → `INSERT (index_code, stock_id, effective_from=as_of, effective_to=NULL, weight)`.
- **drops** = `O − P` → `UPDATE … SET effective_to = as_of WHERE effective_to IS NULL` (only if `as_of > effective_from`).
- **unchanged** = `P ∩ O` → `UPDATE weight` on the open row.
- Idempotent: identical `P` → 0 adds, 0 drops. Re-adding a dropped stock → new open row (closed one is history; `uq_index_constituents_open` allows one open per `(index, stock)`).
- **Unresolved** provider symbol (no `stocks` row) → strict raise (master runs first; fail loud, don't silently drop a member).

### Schema facts (read/write) — `0003`
- `stocks`: `(id, market_id, symbol, isin, company_name, sector, industry, market_cap_bucket, listed_on, delisted_on, is_active, …)`, `UNIQUE(market_id, symbol)`. Master upsert touches `company_name/isin/is_active/updated_at` (dev provider has no sector/industry → leave as-is on update; NULL on insert).
- `index_constituents`: `(id, index_code, symbol→stock_id, effective_from, effective_to, weight numeric(9,6))`, `CHECK (effective_to IS NULL OR effective_to > effective_from)`, `uq_index_constituents_open` (one open per index+stock).
- Current seed (QV-005): 12 stocks, 12 open NIFTY200 rows (`effective_from 2024-01-01`). The dev provider's 5 are a subset — do **not** reconcile against it.

### Reuse map
- `active_universe(session, index_code, market)` — QV-016 repo (assert post-sync membership).
- `list_universe` + `UniverseEntry` + `Provenance`/`LicenseClass` — QV-012 (`interfaces.py`, `models.py`, `adapters/yfinance_dev.py`).
- `run_job`, `run_key`, `JobResult`, `JobOutcome`, `JobRunLedger` — QV-015. Strict-raise + `@app.task(...)` pattern — mirror `jobs/ingest.py` / `jobs/quality.py`.
- `privileged_session_scope` (`core/db.py`), `LoggingEventBus` (`core/events.py`), `IEventBus` (`core/interfaces.py`), `last_completed_session` (`trading_calendar.py`).
- Integration scaffold (seed throwaway market/stocks/constituents under a unique `index_code`, fake provider/bus, cleanup) — copy the shape from `tests/integration/test_data_quality.py` / `test_corporate_actions.py`.

### Boundaries & gates
- `UniverseSyncService` imports no yfinance/pandas; `market_data` stays a DAG leaf; `jobs/universe.py` is a composition root. Confirm `lint-imports` 3/3.
- mypy `--strict`: annotate all signatures; frozen `@dataclass(slots=True)` reports; `Decimal` for weights; add `quantvista.jobs.universe` to the untyped-decorator override (as `jobs.ingest`/`jobs.quality`).
- Coverage ≥ 80% on the new repo fns, the service, and `jobs/universe.py`.

### Memory to update on completion
Extend `market-data-provider-strategy` (agent memory): the three-tier provider posture (fake = tests, yfinance-dev = non-authoritative dev, licensed = authoritative NIFTY-200 + weights via QV-072) is now realized in the `list_universe` sync path.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN per task)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (101 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf; `UniverseSyncService` imports no yfinance) ·
  `pytest --cov` → **198 passed** (9 new), TOTAL coverage **96 %** (new/changed: `jobs/universe.py` 100 %,
  `services.py` 100 %, `models.py` 100 %, `repositories.py` 99 %, `adapters/yfinance_dev.py` 90 %).

### Completion Notes List

- **Delivered the sync mechanism (Option 1, user-chosen).** Two idempotent, provider-agnostic jobs behind
  the existing `IMarketDataProvider.list_universe` seam: `sync_stock_master` (upsert-only catalogue) and
  `sync_index_constituents` (survivorship-free PIT reconcile — open adds, close drops, refresh weights).
  Verified end-to-end with a **fake provider** (master insert/update/idempotent; reconstitution
  {A,B,C}→{B,C,D}: A closed w/ `effective_to`, D opened, B/C weights; idempotent; unresolved-abort;
  strict run-fail via `run_job`). **No new migration.**
- **Not run against the dev stub.** `YFinanceDevProvider.list_universe` is a non-authoritative 5-symbol
  list; neither job is on `beat_schedule`. Real NIFTY-200 + weights → licensed vendor (QV-072). The seeded
  12 stay the dev universe.
- **Correctness catch during build:** an *unresolved* provider symbol (no `stocks` row) would drop out of
  the provider set and get wrongly **closed** as a "drop". `reconcile_constituents` now **aborts untouched**
  when anything is unresolved (returns the list; the service logs + skips the event; the job raises) — a
  half-known provider view never mutates membership. Integration-tested (nothing closed/opened, no event).
- **Seam refinements (design-only):** `UniverseEntry` gained optional `weight: Decimal | None = None`
  (threaded provider → open row; dev = None); `YFinanceDevProvider.list_universe` now returns the
  **canonical** symbol (strips its own `.NS`, venue stays in `exchange`) with a non-authoritative docstring,
  so it maps 1:1 to `stocks.symbol`.
- **Shape mirrors QV-016/017/018:** service returns house-style reports (`StockMasterReport`,
  `ConstituentsReport`); tasks wrap `run_job` with a strict raise (`UniverseSyncError`). **No
  security-reviewer** — parameterized SQL, no auth/PII/user-input, internal-dev provider.
- **Weight update is a true no-op when unchanged** (user-requested refinement): the `_UPDATE_WEIGHT_SQL`
  carries `AND weight IS DISTINCT FROM :weight`, so an identical re-sync writes no row (and the guard also
  handles the `NULL ↔ value` transition). Proven by a test asserting the row's `xmin` (Postgres write
  marker) is unchanged across a second identical sync.
- **Memory updated:** `market-data-provider-strategy` extended with the three-tier provider posture now
  realized in the `list_universe` sync path.

### File List

**New**
- `backend/src/quantvista/jobs/universe.py` — `sync_stock_master` + `sync_index_constituents` tasks +
  `sync_index_constituents_now` + `UniverseSyncError`, under `run_job`.
- `backend/tests/integration/test_universe_sync.py` — master + PIT reconcile over real Postgres (fake provider).

**Modified**
- `backend/src/quantvista/market_data/models.py` — `UniverseEntry.weight` (optional).
- `backend/src/quantvista/market_data/adapters/yfinance_dev.py` — `list_universe` returns canonical symbols
  (`_canonical` helper) + non-authoritative labeling.
- `backend/src/quantvista/market_data/repositories.py` — `upsert_stocks` + `reconcile_constituents` +
  `ConstituentCounts`.
- `backend/src/quantvista/market_data/services.py` — `UniverseSyncService` + `StockMasterReport` +
  `ConstituentsReport`.
- `backend/tests/test_market_data_provider.py` — canonical-symbol assertion for `list_universe`.
- `backend/pyproject.toml` — mypy untyped-decorator override extended to `quantvista.jobs.universe`.

### Change Log

- **2026-07-04 — QV-019 universe sync (master + PIT constituents).** Added `sync_stock_master` (upsert
  catalogue) and `sync_index_constituents` (survivorship-free PIT reconcile: open adds / close drops /
  set weights) behind the existing `list_universe` seam; provider-agnostic service + `run_job` tasks with a
  strict unresolved-abort. `UniverseEntry` gained optional `weight`; the dev adapter now emits canonical
  symbols and is labeled non-authoritative. Verified with a fake provider (reconstitution, idempotency,
  unresolved-abort); not run against the dev stub / not scheduled (→ QV-072 / PV-005). 198 tests green,
  coverage 96 %; ruff/mypy-strict/import-linter clean. No new migration.

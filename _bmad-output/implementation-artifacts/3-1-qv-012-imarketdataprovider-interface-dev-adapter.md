---
baseline_commit: 9d3354b4c951a4939ad2e93cc6e5657891d34d47
---

# Story 3.1: QV-012 — IMarketDataProvider interface + dev adapter

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **all external market data to enter through one vendor-agnostic `IMarketDataProvider` interface, with an internal-only dev adapter (yfinance) that stamps provenance/licensing on every datum**,
so that **vendors can be swapped without touching analytics, and a non-commercial source can never silently leak into a paid tier**.

> Canonical ID **QV-012** · Epic 3 (EPIC-DATA) · `[DATA]` · 5pts · Sprint 01 · depends: **QV-001** (done)
> Authoritative detail: `plans/sprints/sprint-01-data-backbone-i.md` §QV-012. Licensing + provider seam: `plans/03-data-architecture.md` §1 (READ FIRST) + §4 schema field shapes. Project rule **#8** (data licensing) + **#3** (module boundaries).

## ⚠️ Read this first — scope + the licensing guardrail (CRITICAL)

This story is the **provider abstraction only** — an interface, its return DTOs, and one internal dev adapter. **No database, no migrations, no ingestion jobs.**

- **In scope:** expand `market_data/interfaces.py` `IMarketDataProvider` to 5 methods; define vendor-agnostic **DTOs** (frozen dataclasses, `Decimal` money) carrying **provenance** (`source`, `source_url`, `license_class`); implement a **yfinance dev adapter** that maps Yahoo data → those DTOs and stamps `license_class='non_commercial_dev'`.
- **NOT this story:** DB schema for `stocks`/`daily_prices`/… (→ QV-013/QV-014), ingestion/persistence jobs (→ QV-016+), `stock_id` FKs (the provider works in **symbols** — the DB doesn't exist yet), caching, the licensed India vendor adapter (→ QV-072).
- **THE GUARDRAIL (project rule #8, `03` §1):** yfinance/Yahoo is **allowed for internal dev only — never behind a paying tier** (not licensed for commercial redistribution). The dev adapter MUST hard-stamp `license_class='non_commercial_dev'` on every DTO, and yfinance MUST be an **optional dependency** (a `dev-data` extra), so it is not pulled into the production image by default. This is a locked, audited constraint — not a preference.

## Acceptance Criteria

1. **`IMarketDataProvider` defines the five methods** (in `market_data/interfaces.py`, replacing the QV-001 `fetch_daily_prices` stub): `get_prices`, `get_corporate_actions`, `get_fundamentals`, `get_shareholding`, `list_universe`. It stays a `@runtime_checkable` `Protocol`. Methods are **symbol-based** (no `stock_id` — no DB yet) and typed against the DTOs from AC #2. Suggested signatures (dev may refine, keep them vendor-neutral and typed):
   - `get_prices(symbol: str, start: date, end: date) -> Sequence[PriceBar]`
   - `get_corporate_actions(symbol: str, start: date, end: date) -> Sequence[CorporateAction]`
   - `get_fundamentals(symbol: str) -> Sequence[FundamentalSnapshot]`
   - `get_shareholding(symbol: str) -> Sequence[ShareholdingSnapshot]`
   - `list_universe(index_code: str = "NIFTY200") -> Sequence[UniverseEntry]`
2. **Vendor-agnostic DTOs** (frozen, slotted dataclasses in a new `market_data/models.py` content — currently a placeholder) mirror the eventual `03` §4 schema fields, **money/ratios as `Decimal` (never `float`)**, dates as `date`, volume as `int`, optional fields `X | None`:
   - `PriceBar(symbol, date, open, high, low, close, adj_close: Decimal|None, volume: int, provenance)`
   - `CorporateAction(symbol, ex_date, action_type: CorporateActionType, ratio_or_amount: Decimal, details: dict, provenance)`
   - `FundamentalSnapshot(symbol, period_end: date|None, statement_type: str|None, pe/forward_pe/pb/roe/roce/debt_equity: Decimal|None, provenance)`
   - `ShareholdingSnapshot(symbol, as_of_date, promoter_holding/fii_holding/dii_holding/public_holding/pledged_pct: Decimal|None, provenance)`
   - `UniverseEntry(symbol, name, isin: str|None, exchange: str, is_active: bool, provenance)`
   - `Provenance(source: str, source_url: str|None, license_class: LicenseClass)` and an enum `LicenseClass` with at least `NON_COMMERCIAL_DEV = "non_commercial_dev"` (future-proofed for `COMMERCIAL_LICENSED`). `CorporateActionType` enum: `SPLIT`, `BONUS`, `DIVIDEND`.
3. **yfinance dev adapter** (`market_data/adapters/yfinance_dev.py`, new) implements `IMarketDataProvider`, maps Yahoo responses → the DTOs, and **stamps `license_class=LicenseClass.NON_COMMERCIAL_DEV`** + a real `source`/`source_url` (`"yfinance"` / the Yahoo Finance URL) on every returned DTO. yfinance is **lazily imported** inside the adapter; a missing yfinance raises a clear, actionable error (not an `ImportError` at module import). The yfinance client is **injectable** (constructor param / factory) so tests never hit the network. Best-effort/unreliable Yahoo fields degrade to `None`, never crash (see `03` §1: "unreliable fields").
4. **Licensing hard-stamp is enforced by a test** (rule #8): a unit test asserts every DTO the dev adapter returns has `provenance.license_class == LicenseClass.NON_COMMERCIAL_DEV`. This is the auditable guarantee that a non-commercial source is labelled as such.
5. **yfinance is an optional `dev-data` extra** in `backend/pyproject.toml` (`[project.optional-dependencies].dev-data = ["yfinance>=0.2"]`), **not** a core runtime dependency — the provider abstraction is what makes the vendor swappable, and this keeps a non-commercial lib out of the default/prod install. A `[[tool.mypy.overrides]]` entry treats `yfinance` as untyped (mirrors the `celery` pattern). Document the extra in the module docstring + `.env`/README as needed.
6. **Module boundary intact (rule #3):** `market_data` imports only `core`/`schemas` (+ stdlib + yfinance in the adapter) — no other bounded context. `import-linter` stays green (market_data/news independence + layered DAG). DTOs live in `market_data`; the adapter in `market_data/adapters/`.
7. **Tests ≥ 80 % + gates green:** unit tests with a **fake/injected yfinance** (no network) cover: each method maps to the right DTO shape; `Decimal` types (never `float`) for money; provenance stamped incl. the license class (AC #4); `isinstance(adapter, IMarketDataProvider)` holds (runtime_checkable conformance); unreliable/missing fields → `None` without raising; empty/unknown symbol handled. `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest --cov` (≥80%) all green locally and in CI.

## Tasks / Subtasks

- [x] **Task 1 — DTOs + enums** (AC: #2)
  - [x] Fill `market_data/models.py` with frozen (`@dataclass(frozen=True, slots=True)`) DTOs: `Provenance`, `PriceBar`, `CorporateAction`, `FundamentalSnapshot`, `ShareholdingSnapshot`, `UniverseEntry`; enums `LicenseClass`, `CorporateActionType`. `Decimal` for all money/ratios, `date` for dates, `X | None` for optionals. `from __future__ import annotations`.
  - [x] Unit-test DTO construction + immutability (frozen) + that money fields accept `Decimal`.
- [x] **Task 2 — Expand the provider interface** (AC: #1, #6)
  - [x] In `market_data/interfaces.py`, replace `IMarketDataProvider.fetch_daily_prices` with the 5 typed, symbol-based methods returning the DTOs. Keep `@runtime_checkable Protocol`. Leave `IPriceRepository`/`IFundamentalsRepository` as-is (out of scope). Confirm `lint-imports` stays green.
- [x] **Task 3 — yfinance dev adapter** (AC: #3, #5)
  - [x] Add `yfinance>=0.2` under a new `dev-data` optional-dependency extra in `pyproject.toml`; add a `[[tool.mypy.overrides]]` `ignore_missing_imports` for `yfinance`.
  - [x] Create `market_data/adapters/__init__.py` + `market_data/adapters/yfinance_dev.py`: `YFinanceDevProvider` implementing `IMarketDataProvider`. Lazy-import yfinance (clear error if absent); accept an injectable ticker factory (default `yf.Ticker`) so tests inject a fake. Map `.history(start,end)` → `PriceBar`s; `.actions`/`.splits`/`.dividends` → `CorporateAction`s; `.info` → `FundamentalSnapshot`; `.institutional_holders`/`.major_holders` (best-effort) → `ShareholdingSnapshot`; a static/curated NIFTY200 symbol list or `.info`-derived → `UniverseEntry`. **Convert all numerics to `Decimal` via `str()`** (never `float→Decimal` directly). Stamp provenance with `license_class=NON_COMMERCIAL_DEV`.
  - [x] Best-effort field handling: missing/NaN Yahoo fields → `None`; never raise on a sparse response.
- [x] **Task 4 — Tests** (AC: #4, #7)
  - [x] `tests/test_market_data_provider.py`: inject a fake ticker (canned DataFrame-like / dict fixtures — no network) and assert DTO mapping, `Decimal` types, provenance + **license_class hard-stamp** (AC #4), `isinstance(provider, IMarketDataProvider)`, sparse-field→`None`, unknown symbol.
  - [x] Keep tests network-free and deterministic (AAA, behavior-named). Ensure they don't require the `dev-data` extra to *run the mapping logic* — mock at the ticker-factory boundary so the suite passes even where yfinance isn't installed (import the adapter but inject a fake; or skip only the live path).
- [x] **Task 5 — Gates + docs** (AC: #6, #7)
  - [x] Run `ruff check`, `ruff format --check`, `mypy` (strict), `lint-imports`, `pytest --cov=src` (≥80%). Fix all findings; record commands/output in the Dev Agent Record.
  - [x] Note the `dev-data` extra + the licensing guardrail in the adapter docstring; if any pending-verification applies (none expected — pure code) skip. Reconcile QV-008/QV-009 → done and the PV-ledger clarity note ride on this branch (housekeeping).

## Dev Notes

### Scope discipline
QV-012 = **the seam**: interface + DTOs + one internal dev adapter, fully unit-tested with **no network**. **Not this story:** any DB table/migration (QV-013 `stocks`/`index_constituents`/`corporate_actions`, QV-014 `daily_prices`), ingestion jobs (QV-016 `ingest_daily_prices` etc.), `stock_id`/FKs, adjusted-close computation (QV-017), the licensed vendor adapter (QV-072). The provider deals in **symbols + `date` ranges**, returning DTOs — persistence maps DTOs→rows later.

### THE licensing guardrail (do not skip — rule #8, `03` §1)
- yfinance/Yahoo: **internal dev only, never a paying tier.** The adapter hard-stamps `license_class='non_commercial_dev'`; AC #4 test enforces it. `03` §1 rule 3 (monetization gate): Free/Pro/Quant must not be served from a non-commercial source. This abstraction is *why* the vendor decision (O2 / M-DATA / QV-072) is deferrable.
- Provenance = the audit trail (`03` §1 rule 2): `source`, `source_url`, `license_class` on every datum (the eventual `ingested_at`/`as_of_date` are stamped at persistence, QV-016 — not here).
- yfinance as an **optional extra** enforces the separation at the packaging layer: prod images don't install it by default.

### What already exists / context to build on
- **`market_data/interfaces.py`** — has a QV-001 stub `IMarketDataProvider.fetch_daily_prices(symbol, on) -> object` (replace it) plus `IPriceRepository`/`IFundamentalsRepository` (leave — they're for QV-014+). All `@runtime_checkable Protocol`.
- **`market_data/models.py`, `repositories.py`, `services.py`** — empty placeholders (docstring only). Put DTOs in `models.py`; the adapter goes in a new `market_data/adapters/` subpackage. `services.py`/`repositories.py` stay empty this story.
- **`core/`** is the only allowed import target (foundation). Do **not** import `identity`/`analytics`/etc. `schemas/envelope.py` is unrelated (API layer) — DTOs here are domain objects, not API envelopes.
- **Money convention (rule, project-context):** `Decimal`/`NUMERIC`, **never `float`**. yfinance returns floats/np.float64 → convert via `Decimal(str(x))` to avoid binary-float artefacts. NaN → `None`.
- **Modern typing:** `X | None`, `list[...]`/`Sequence[...]`, `from __future__ import annotations` (matches the repo).
- **No prior Epic-3 story exists** (QV-012 is the first) — no previous-story file to inherit from; the closest patterns are the identity DTOs/`Protocol` style (`identity/models.py`, `identity/interfaces.py`) and the `celery` mypy-override precedent in `pyproject.toml`.

### Reuse — do NOT hand-roll (research & reuse rule)
- Use **yfinance** for the dev adapter (the plan names it explicitly). Don't hand-roll Yahoo scraping. Map at the adapter edge into our typed DTOs so the rest of the codebase never sees a yfinance/pandas type.

### Testing notes
- **No network in tests.** Inject a fake ticker object (or ticker factory) exposing the attributes the adapter reads (`.history()`, `.actions`, `.info`, `.institutional_holders`, …) with canned values. Assert: DTO field mapping, `isinstance(x.close, Decimal)`, provenance + license class, sparse→`None`, `isinstance(provider, IMarketDataProvider)`. AAA, behavior-named. Coverage ≥80% (project gate).
- If a live-yfinance smoke path is added, guard it behind a marker/skip so CI (no `dev-data` extra, no network) stays green.

### Project Structure Notes
- **New:** `market_data/adapters/__init__.py`, `market_data/adapters/yfinance_dev.py`, `tests/test_market_data_provider.py` (and/or `tests/test_market_data_models.py`).
- **Modified:** `market_data/interfaces.py` (5 methods), `market_data/models.py` (DTOs), `backend/pyproject.toml` (`dev-data` extra + yfinance mypy override).
- **Housekeeping on this branch:** `sprint-status.yaml` QV-008/QV-009 → `done` reconcile; `docs/pending-verifications.md` "two kinds of deferral" clarity note (carried over uncommitted).
- Keep files 200–400 lines (800 max); one concern per module.

### References
- [Source: plans/sprints/sprint-01-data-backbone-i.md#QV-012] — story + AC (5 interface methods; dev adapter; provenance `source`/`source_url`/`license_class='non_commercial_dev'`).
- [Source: plans/03-data-architecture.md#1-data-licensing--sourcing] — **READ FIRST**: yfinance internal-only; provider abstraction (rule 1); provenance (rule 2); monetization gate (rule 3); `license_class`.
- [Source: plans/03-data-architecture.md#4] — schema field shapes for `daily_prices`, `corporate_actions`, `fundamentals`, `shareholding`, `index_constituents`, `stocks` (DTO fields mirror these).
- [Source: _bmad-output/project-context.md] — rule #8 (licensing/`IMarketDataProvider`), rule #3 (module boundaries/import-linter), rule #1 (global vs tenant data — market data is global), Decimal-not-float, modern typing.
- [Source: backend/src/quantvista/market_data/interfaces.py] — existing stub to replace + repo protocols to keep.
- [Source: backend/pyproject.toml] — `celery` mypy-override precedent for the yfinance untyped override; optional-dependencies pattern (`dev` extra).

### Latest Tech (verified via Context7 — yfinance)
- API surface: `yf.Ticker(symbol)` → `.history(start=<date>, end=<date>, auto_adjust=False)` returns a pandas DataFrame with `Open/High/Low/Close/Adj Close/Volume` (keep `auto_adjust=False` so `close` and `adj_close` are distinct — adjusted-close correctness is QV-017's concern, but preserve both). `.actions` / `.dividends` / `.splits` for corporate actions; `.info` (dict: `trailingPE`, `forwardPE`, `priceToBook`, `returnOnEquity`, …) for fundamentals; `.institutional_holders` / `.major_holders` for (best-effort, often sparse for India) shareholding.
- **Version floor:** `yfinance>=0.2` (confirm current stable at implementation). Yahoo fields are unreliable/rate-limited by design (`03` §1) — map defensively, NaN/missing → `None`. Convert numerics with `Decimal(str(value))`.
- yfinance ships no `py.typed`; add the mypy override. Import it lazily inside the adapter so the package (and tests using injected fakes) work without the `dev-data` extra installed.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow)

### Debug Log References

Final gate run (all green; yfinance intentionally NOT installed → proves lazy-import/injection):
- `python -c "import yfinance"` → ModuleNotFoundError (expected; it's the optional `dev-data` extra)
- `ruff check .` + `ruff format --check .` → clean
- `mypy` (strict) → Success: no issues found in 78 source files
- `lint-imports` → Contracts: 3 kept, 0 broken (market_data stays a leaf; no cross-context imports)
- `pytest --cov=src` → **104 passed**; **TOTAL coverage 94 %** (market_data modules 92–100 %; the
  uncovered `yfinance_dev` lines are the real-network default ticker factory, deliberately not exercised)

### Completion Notes List

- **Pure seam, no DB:** delivered the interface (5 symbol-based methods), vendor-neutral frozen DTOs,
  and the yfinance dev adapter. No schema/migrations/ingestion (those are QV-013/014/016).
- **Licensing guardrail (rule #8) enforced in code + test:** every DTO the adapter emits is hard-stamped
  `license_class=NON_COMMERCIAL_DEV`; `test_get_prices_maps_rows_to_decimal_bars_with_dev_license` +
  the fundamentals/universe tests assert it. yfinance is an **optional `dev-data` extra**, imported
  lazily inside the adapter → not in the default/prod install; the whole test suite runs without it.
- **Network-free tests:** the ticker factory is injectable; tests pass a `_FakeTicker`/`_FakeFrame`
  mimicking the slice of the pandas API the adapter uses (`.history().iterrows()`, `.actions`, `.info`).
- **Money rule:** all numerics converted via `Decimal(str(x))`; NaN/`pd.NA`/None → `None` (never a
  float artefact, never a crash on Yahoo's sparse fields).
- **Design choices:** `auto_adjust=False` keeps `close`/`adj_close` distinct (adjustment is QV-017);
  shareholding is best-effort from `.info` (Yahoo can't split FII/DII → `None`; absent → `[]`);
  `list_universe` returns a small curated NSE dev set (the authoritative PIT NIFTY200 sync is QV-019).
- **No security-reviewer pass:** unlike QV-009 this story has no auth/PII/secret/user-input surface;
  the one real risk (non-commercial data leaking to a paid tier) is covered by the AC #4 test + the
  optional-extra packaging separation.
- **Housekeeping bundled on this branch:** QV-008 & QV-009 reconciled `review → done` in
  sprint-status; the "two kinds of deferral" clarity note added to `docs/pending-verifications.md`.

### File List

**New**
- `backend/src/quantvista/market_data/adapters/__init__.py`
- `backend/src/quantvista/market_data/adapters/yfinance_dev.py` — `YFinanceDevProvider` + `Decimal`/NaN helpers.
- `backend/tests/test_market_data_models.py`
- `backend/tests/test_market_data_provider.py`

**Modified**
- `backend/src/quantvista/market_data/models.py` — vendor-agnostic DTOs + `LicenseClass`/`CorporateActionType` enums.
- `backend/src/quantvista/market_data/interfaces.py` — `IMarketDataProvider` expanded to 5 methods.
- `backend/pyproject.toml` — `dev-data` optional extra (`yfinance>=0.2`) + yfinance mypy override.

**Housekeeping (bundled, per branch convention)**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-008/QV-009 → done; epic-3 in-progress; QV-012 status.
- `docs/pending-verifications.md` — "two kinds of deferral" clarity note.

### Change Log

- **2026-07-02 — QV-012 IMarketDataProvider interface + dev adapter.** Added the market-data provider
  seam: `IMarketDataProvider` (5 symbol-based methods), vendor-neutral frozen DTOs (`Decimal` money +
  `Provenance`/`LicenseClass`), and an internal-only yfinance dev adapter that hard-stamps
  `non_commercial_dev` and maps Yahoo → DTOs defensively. yfinance is an optional `dev-data` extra
  (lazy import, injectable factory → network-free tests). 104 tests green, coverage 94 %,
  ruff/mypy-strict/import-linter clean. No DB/migrations (QV-013+). Reconciled QV-008/QV-009 → done.

---
baseline_commit: 4f3db7c2c7b3a30e15e0f6d6520f7247d825d380
---

# Story 3.14: QV-026 — sync_macro_series (rates / inflation / GDP)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the analytics layer**,
I want **macro time series (rates, inflation, GDP) ingested into a generic `macro_series` table**,
so that **macro context is available to factors / ML, kept current and idempotent**.

> Canonical ID **QV-026** · Epic 3 (EPIC-DATA) · `[DATA]` · 3pts · Sprint 02 · depends: **QV-015 ✅** (job framework)
> Authoritative: `plans/03` §4.1 (`macro_series` DDL: `id, series_code, date, value, source`, unique `(series_code, date)`) · `06` §2 catalog (`sync_macro_series`, Daily/weekly, key `macro:{series}:{date}`, **emits —**). `03`: FRED is free + **redistributable** (attribution); RBI/MOSPI public.

## ⚠️ Read this first — the DDL already exists (verify, do NOT re-create)

`macro_series` is already defined in **`0003_reference_market.py`** (applied; `id uuid, series_code text, date date, value numeric(20,6), source text, ingested_at`, `UNIQUE (series_code, date)`, global/no RLS). **No new migration.** QV-026's net code is the provider seam + a real FRED adapter + the upsert repository + the `sync_macro_series` service/task.

## Locked decisions

- **TWO real providers, split by what each serves freshly (owner-confirmed after live probing):** **FRED = US/global only** (DGS10 next-day fresh; free key) and **World Bank = India + cross-country annual** (no API key; current-year). Live probing proved FRED's *India* series are annual + lag >1 yr (re-hosted World Bank/IMF — all >200 d stale), so India is routed to World Bank instead. Both are **live-verified** (see Dev Agent Record) — **no PV needed**. RBI/MOSPI (monthly/daily fresh India) are tracked scope-deferrals (`docs/pending-verifications.md` → Deferred data sources).
- **Three-layer design (owner-confirmed): `MacroSyncService` → `MacroSeries` catalog → generic `IMacroProvider.get_series`.** The **provider seam is generic** — `get_series(provider_code, start, end) -> Sequence[MacroObservation]` — because macro sources expose 10³–10⁶ series; per-metric methods (`get_gdp/get_cpi`) don't scale. The app never touches raw codes: a typed **`MacroSeries` enum** (catalog) maps canonical concepts → provider codes, and `MacroSyncService` drives sync (with optional semantic helpers later). `MacroObservation` DTO: `series_code, date, value: Decimal | None, source`.
- **Store the CANONICAL series key, not the provider code** (owner-approved refinement). `macro_series.series_code` is what downstream factors reference, so it must be **provider-stable**: we store the canonical name (e.g. `"INDIA_CPI"`), while the provider code (FRED `"INDCPIALLMINMEI"` or World Bank `"FP.CPI.TOTL"`) is a per-provider mapping used only to fetch. The service **re-stamps the canonical `series_code`** before upsert — proven live: World Bank returns rows tagged with its own code, persisted under `"INDIA_CPI"`. Routing (`_provider_for`) sends US_* → FRED, INDIA_* → World Bank; the catalog partitions cleanly (test-asserted).
- **Generic upsert keyed `(series_code, date)`** (like `daily_prices`). Re-polling updates in place; idempotent. `value` stays `Decimal` (`numeric(20,6)`).
- **Configurable catalog; no event** (per the `06` catalog "—"). `Settings.macro_series` default = a small set of `MacroSeries` (10y Treasury, Fed Funds, US CPI, India CPI, India GDP — all FRED-sourced now); the task syncs each. `sync_macro_series` publishes nothing (no downstream consumer named).
- **Fast-follow roadmap** (owner's source map): **RBI** + **MOSPI** (authoritative Indian macro), **World Bank** + **IMF** (cross-country) as drop-in adapters behind the same generic seam — each its own story. FRED-first because it's free + redistributable and already carries India series.
- **Housed in `market_data` (external-data ingestion leaf) + `jobs`.** Macro is external time-series ingestion, same shape as the price pipeline; keeps the DAG unchanged (`market_data` leaf, `jobs` composition root). A dedicated `macro` context can be extracted later if it grows. Global table → **privileged** engine.

## Acceptance Criteria

1. **Schema conformance confirmed + documented.** Verify `0003` `macro_series` (`series_code, date, value NUMERIC, source`, `UNIQUE (series_code, date)`, global). Record conformance in the Dev Agent Record. **No duplicate migration.**
2. **Provider seam + real FRED adapter.** `IMacroProvider.get_series(series_code, start, end) -> Sequence[MacroObservation]`; `MacroObservation(series_code, date, value: Decimal | None, source)`. `FredMacroProvider` fetches `fred/series/observations` (stdlib `urllib`, `Settings.fred_api_key`), parses JSON → observations (`.` value → `None`), stamps `source="fred"`. **Network-free unit test** with a stubbed HTTP payload; a clear error if `fred_api_key` is unset.
3. **Upsert repository.** `upsert_macro_series(session, observations) -> int` — `INSERT … ON CONFLICT (series_code, date) DO UPDATE value/source/ingested_at`. `Decimal`; `[]` → 0. Idempotent.
4. **Sync service + task.** `MacroSyncService(provider)`; `sync(series_code, start, end) -> MacroSyncReport` (fetch → upsert; tally `observations_upserted`). A Celery task `sync_macro_series(series_code, date_iso=None)` wrapped by `run_job` (`run_key = macro:{series}:{date}`, QV-015; recorded in `jobs_runs`); default window ends at `date` (a lookback so re-runs refresh recent points). No event.
5. **Boundaries.** Service imports no concrete adapter; `market_data` stays a DAG leaf; global table → privileged engine. No new dependency (stdlib `urllib`). **No migration**.
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on new code. **Unit:** FRED JSON parse (stubbed HTTP) incl. `.`→None + missing-key error. **Integration** (real Postgres, fake provider): `sync` upserts observations; idempotent re-run (same `(series_code, date)` → updated in place, row count stable); the task via `run_job` (`jobs_runs` recorded).

## Tasks / Subtasks

- [x] **Task 1 — verify schema conformance (§4.1)** (AC: #1)
  - [x] Read `0003` `macro_series` + `03` §4.1; field/constraint conformance note in the Dev Agent Record. Confirm **no** migration change.
- [x] **Task 2 — provider seam + FRED adapter** (AC: #2)
  - [x] `market_data/macro.py` (new): `MacroObservation` frozen dataclass; `IMacroProvider` Protocol; `FredMacroProvider` (stdlib `urllib.request`, `fred_api_key`, JSON parse, `.`→None, `source="fred"`; raise a clear error if the key is unset). `Settings.fred_api_key: str | None` + `Settings.macro_series` default (FRED codes). Unit test with a stubbed `urlopen`.
- [x] **Task 3 — upsert repository** (AC: #3, #5)
  - [x] `repositories.py`: `upsert_macro_series(session, observations: Sequence[MacroObservation]) -> int` (`ON CONFLICT (series_code, date) DO UPDATE`).
- [x] **Task 4 — sync service + task** (AC: #4)
  - [x] `market_data/services.py`: `MacroSyncReport` + `MacroSyncService(provider)`; `sync(series_code, start, end)`. `jobs/macro.py` (new): `sync_macro_series(series_code, date_iso=None)` task under `run_job` (`macro:{series}:{date}`), constructing `FredMacroProvider`. Add `quantvista.jobs.macro` to the mypy untyped-decorator override. No beat entry (→ PV-006 cadence).
- [x] **Task 5 — tests + gates + reconcile + PV** (AC: #6)
  - [x] `tests/test_macro_provider.py` (FRED parse, stubbed HTTP) + `tests/integration/test_macro_sync.py` (fake provider: upsert + idempotent + task `run_job`). Add **PV-006** (live FRED pull needs `FRED_API_KEY`) to `docs/pending-verifications.md`. Run all gates; reconcile QV-025 → done (already applied on this branch).

## Dev Notes

### Scope discipline
QV-026 = verify `macro_series` + a provider-agnostic macro ingestion (real FRED adapter, network-free tested) + upsert + the `sync_macro_series` job. **Not this story:** RBI/MOSPI adapters (future, different APIs — the seam makes them drop-in), factors/ML consuming macro (Epic 4+), the live FRED pull (→ **PV-006**, needs `FRED_API_KEY`), scheduling on beat (→ PV-005/006). **No migration.**

### FRED adapter (stdlib, network-free tested)
`GET https://api.stlouisfed.org/fred/series/observations?series_id=<code>&api_key=<key>&file_type=json&observation_start=<start>&observation_end=<end>` → `{"observations":[{"date":"YYYY-MM-DD","value":"1.23" | "."}, …]}`. Parse: `value="."` (FRED's missing marker) → `None`; else `Decimal(value)`. `source="fred"`. Use `urllib.request.urlopen` (stdlib) so the default install needs no HTTP client; the unit test monkeypatches `urlopen` to return a canned JSON payload (network-free, like QV-012's fake `Ticker`). Missing `fred_api_key` → a clear `RuntimeError`.

### Reuse map
- `MacroObservation` DTO 1:1 → the `macro_series` columns. `upsert_daily_prices`/`upsert_shareholding` are the upsert template (`ON CONFLICT … DO UPDATE`).
- `run_job`/`run_key`/`JobResult`/`JobRunLedger`, `@app.task(...)`, `privileged_session_scope`, `last_completed_session` — mirror the sibling ingest tasks (no event, like `ingest_shareholding`).
- Integration seed: no universe needed — macro is series-keyed; the fake provider supplies observations; cleanup by `series_code` + run_key.

### Boundaries & gates
- `market_data/macro.py` imports stdlib + core only (`urllib`, `Settings`); the service imports no concrete adapter; `market_data` stays a DAG leaf (`lint-imports` 3/3). `jobs/macro.py` is a composition root — add to the mypy untyped-decorator override. `value` stays `Decimal`. Coverage ≥ 80% on the new adapter + repo + service.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (126 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf; the service imports no concrete adapter) ·
  `pytest` → **261 passed, 4 skipped** (Kafka broker down + 3 promtool). Coverage 94 %; new:
  `market_data/macro.py` **90 %**, `jobs/macro.py` 81 % (uncovered = the daily Celery task body, tested via `_run_macro`).
- **RED confirmed** first: `test_macro_provider.py` failed with `ModuleNotFoundError: quantvista.market_data.macro`.

### Completion Notes List — Task 1 schema conformance (`0003` vs `03` §4.1)

**`macro_series` conforms — NO migration change.** `0003_reference_market.py`: `id uuid, series_code text,
date date, value numeric(20,6), source text, ingested_at`, `UNIQUE (series_code, date)`, global (no RLS).
Matches `03` §4.1 (`id, series_code, date, value NUMERIC, source`). No deviation.

### Completion Notes List — LIVE verification, BOTH providers (no PV needed)

**Verified against both real APIs** with the owner's FRED key (gitignored `backend/.env`) + World Bank's
keyless API — so **no pending-verification required** (unlike the AWS/Docker PVs). Routed by `_provider_for`:
- **FRED (US/global):** `US_10Y` (DGS10) **1247 values**, latest **2026-07-01 = 4.48** · `US_FED_FUNDS` 3.63.
- **World Bank (India):** `INDIA_INFLATION`/`INDIA_GDP`/`INDIA_CPI` — all with a **2025** value (2.40 % /
  $3.96 T / 233.06), 5 y history each, **no API key**.
- **The finding that reshaped the story (owner decision):** live-probing 7 FRED India series showed **none**
  had a point within 200 d — FRED re-hosts *annual, >1 yr-lagged* World Bank/IMF data. So **FRED was
  narrowed to US/global only** and **World Bank added as a second real provider** for India + cross-country
  (current-year annual). Monthly/daily fresh India (CPI monthly, rates) needs **RBI/MOSPI** → tracked as
  scope-deferrals in `docs/pending-verifications.md`. Task lookback widened to **1825 d (5 y)** so annual
  series still refresh; idempotent upsert makes it cheap.
- **certifi TLS:** the live smoke first hit `CERTIFICATE_VERIFY_FAILED` (Homebrew macOS Python ignores the
  system CA store). Fixed in the shared `_HttpJsonProvider` base: SSL context from `certifi.where()`, so TLS
  works on macOS dev + Linux/CI/Docker. `certifi` added as a core dep (was transitive).

### Completion Notes List — implementation

- **Three-layer design** (owner-confirmed): `MacroSyncService` → typed `MacroSeries` catalog → **generic**
  `IMacroProvider.get_series(code)` seam. Per-metric methods (`get_gdp`) don't scale (FRED alone = 800k+
  series). Each provider owns its canonical→code map via `code_for` (`_FRED_CODES` / `_WORLDBANK_CODES`);
  the catalog partitions cleanly across providers (`FRED_SERIES`/`WORLDBANK_SERIES`, test-asserted).
- **Two real providers** sharing an `_HttpJsonProvider` base (certifi TLS + retry): `FredMacroProvider`
  (US/global; `.`→None; clear `RuntimeError` if key unset; `code_for` raises for India) and
  `WorldBankMacroProvider` (India/cross-country; keyless; `[meta, rows]` envelope, year→annual Jan-1 point;
  retries the flaky 502s). `_provider_for` routes US_* → FRED, INDIA_* → World Bank. Both network-free
  unit-tested (stubbed `urlopen`) **and live-verified**.
- **Canonical-key storage** (`market_data/macro.py` 90 %, `services.py`): `macro_series.series_code` stores
  the **canonical** key (e.g. `"INDIA_CPI"`), not the provider code — the service re-stamps it via
  `dataclasses.replace` before upsert, so FRED↔World Bank never changes the stored key. Proven by
  `test_sync_stores_the_canonical_key` (provider-tagged `"FRED_CODE"` → persisted as `"US_10Y"`).
- **`upsert_macro_series`** (`repositories.py`): `ON CONFLICT (series_code, date) DO UPDATE`; `Decimal`;
  idempotent. **`sync_macro_series` task** (`jobs/macro.py`) under `run_job` (`macro:{series}:{date}`,
  recorded in `jobs_runs`), no event (per `06` catalog). Verified over real Postgres + `jobs_runs` row.
- **Not this story:** RBI/MOSPI/World Bank/IMF adapters (drop-in fast-follows behind the same seam),
  factors/ML consuming macro (Epic 4+), beat cadence (→ PV-005/006). **No migration; no security-reviewer**
  (read-only public data, no auth/PII/user-input).

### File List

**New**
- `backend/src/quantvista/market_data/macro.py` — `MacroSeries` catalog, `IMacroProvider` seam, `_HttpJsonProvider` base, `FredMacroProvider` (US/global), `WorldBankMacroProvider` (India/cross-country).
- `backend/src/quantvista/jobs/macro.py` — `sync_macro_series` task + `_provider_for` routing.
- `backend/tests/test_macro_provider.py` — FRED + World Bank parse, FRED-rejects-India, catalog partition (unit, network-free).
- `backend/tests/integration/test_macro_sync.py` — sync + canonical re-stamp + task over real Postgres.

**Modified**
- `backend/src/quantvista/market_data/repositories.py` — `upsert_macro_series`.
- `backend/src/quantvista/market_data/services.py` — `MacroSyncService` + `MacroSyncReport` (canonical re-stamp).
- `backend/src/quantvista/core/config.py` — `fred_api_key` setting.
- `backend/pyproject.toml` — `certifi` core dep + mypy override for `quantvista.jobs.macro`.
- `docs/pending-verifications.md` — Deferred data sources (RBI/MOSPI/IMF scope-deferrals).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-026 status; QV-025 → done (housekeeping).

### Change Log

- **2026-07-05 — QV-026 sync_macro_series.** Verified the pre-existing `0003` `macro_series` schema (no
  migration) and shipped a provider-agnostic macro ingestion: the three-layer `MacroSyncService` →
  `MacroSeries` catalog → generic `IMacroProvider.get_series` seam, with **two real providers** behind a
  shared certifi-backed `_HttpJsonProvider` base — **FredMacroProvider** (US/global) + **WorldBankMacroProvider**
  (India/cross-country, keyless), routed by `_provider_for`. Stores the **canonical** series key
  (provider-stable). **Both live-verified** (FRED 1247 DGS10 points → 4.48; World Bank India 2025 CPI/GDP/
  inflation) — no PV. Narrowed FRED to US/global after live-probing showed its India series lag >1 yr; added
  World Bank for current-year India annual; RBI/MOSPI (monthly/daily fresh India) logged as scope-deferrals.
  Lookback 5 y so annual series refresh. 261 tests green, coverage 94 %; ruff/mypy-strict/import-linter clean.

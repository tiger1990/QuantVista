---
baseline_commit: cd1441de7f0286af82f78b284f2aa5ff27aee6a6
---

# Story 4.3: QV-030 — compute_factors + compute_scores jobs

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **daily factor and score computation triggered by data events**,
so that **scores stay fresh automatically — and a correction re-scores the affected universe (self-heal)**.

> Canonical ID **QV-030** · Epic 4 (EPIC-INTEL) · `[QUANT]` · 5pts · Sprint 03 · depends: **QV-029 ✅** (Normalizer/ScoreEngine)
> Authoritative: `06` §3 catalog — `compute_factors` (after indicators+fundamentals, key `fac:{market}:{date}`, emits `FactorsComputed`) → `compute_scores` (key `score:{universe}:{date}`, emits `ScoresComputed`). Fills QV-027's `recompute_on_correction` seam.

## Locked decisions (owner-reviewed architecture)

- **Factors are the canonical artifact; scores are a projection (split into two engines).** `FactorEngine.compute_factor_values` (statistics — cross-sectional Polars normalization) is the *expensive* step; `ScoreEngine.compute_scores(factor_values)` (business methodology — weighted blend) is *cheap* and re-runnable. They're **separate classes that evolve independently** (a QV-029 refactor: extract `FactorEngine` from `ScoreEngine`; `compute_universe` stays as their composition, keeping QV-029's tests meaningful). `factor_values` becomes the shared foundation dozens of consumers (score-v1/v2, ESG, optimizer, screening, ML) reuse — normalize once, project many.
- **Two event-chained jobs (`06` §3):** `compute_factors(market, date)` → `compute_factor_values` → `upsert_factor_values` → **emit `FactorsComputed`**; `compute_scores(market, date)` → **read the persisted factor snapshot** → `compute_scores` → `upsert_scores` → **emit `ScoresComputed`**. `compute_scores` reads `factor_values` back (never re-normalizes) → enables re-blending with new weights without recomputing factors.
- **Events fire ONLY after durable persistence.** `FactorsComputed` emits **after** `factor_values` is committed; `ScoresComputed` **after** `scores` is committed. A failed persist emits nothing — no phantom events, downstream never observes an in-memory milestone.
- **Idempotent per `(market, date)`.** Under `run_job` (`fac:{market}:{date}` / `score:{market}:{date}`, recorded in `jobs_runs`); upserts make retries produce identical DB state.
- **Snapshot identity is *derived from* `(market, date, model_version)` (v1) — not a true immutable snapshot id.** Those fields identify the *intended* snapshot; two reruns produce the same identifier but distinct row-sets. `compute_scores` reads the factor rows for that `(universe, date)` **in one transaction**; because `compute_factors` writes the whole snapshot **atomically** (all-or-nothing in one txn) and the event fires only post-commit, `compute_scores` reads a *complete, committed* snapshot — no partial/mixed read under READ COMMITTED. The "factors rerun concurrently" case is **acceptable risk for v1**, not "solved": true isolation needs immutable snapshots (`factor_snapshots` table, v2).
- **`MODEL_VERSION` shared by both engines is an *implementation convenience*, not an architectural guarantee.** It keeps factors + scores on the same methodology *as long as a dev bumps it* when normalization changes. The real enforcement — a stored `normalization_version`/fingerprint on `factor_values`, verified on read so a forgotten bump **fails loudly** — needs a column → **v2** (tracked). Events now carry `model_version` so the methodology is at least *visible* per snapshot.
- **Completeness: atomic writes, not a row-count gate.** A partial snapshot can't be committed or read (atomic txn), so the "emit only if `rows == universe × factors`" gate isn't needed — and would *misfire* on our legitimate missing-data model (a stock without a filing has fewer rows by design, coverage < 100 %). Instead `FactorsComputed` carries `stock_count` + `factor_count` so downstream can judge completeness.
- **Self-heal = invalidate + recompute the factor *snapshot*, dataset-level (not per-stock).** `recompute_on_correction(stock_id, period_end)` (QV-027 seam) now resolves the stock's market and **enqueues `compute_factors(market, current_session)`** → cascades to `compute_scores` → re-scores the whole current cross-section (scoring is cross-sectional, so one stock's correction refreshes the universe). Re-scoring *historical* dates is a documented future enhancement.
- **Event chain wired end-to-end:** `IndicatorsComputed → compute_factors → FactorsComputed → compute_scores → ScoresComputed`. Thin consumers enqueue (QV-025 pattern), registered in `register_pipeline_consumers`.
- **Deferred v2 infra (tracked — `scoring-methodology-roadmap`):** a real `factor_snapshots` table (+ `universe_hash`) for full race-proof isolation, and a `normalization_version` column on `factor_values` so `compute_scores` can *verify* `factor_values.version == expected` and fail loudly. Not v1 (need migrations; `0006` `factor_values` has no version column). **No migration this story.**

## Acceptance Criteria

1. **Engine split.** `FactorEngine.compute_factor_values(session, universe, as_of) -> dict[UUID, list[FactorValue]]` (normalize half) + `ScoreEngine.compute_scores(factor_values, as_of) -> list[StockScore]` (blend half). `compute_universe` = the composition (QV-029 behaviour preserved; existing tests green). Decomposition-sums-to-composite unchanged.
2. **`compute_factors(market, date)` task.** Resolve universe → `compute_factor_values` → `upsert_factor_values` → **emit `FactorsComputed{market, date, stocks}` after commit**. `run_job` `fac:{market}:{date}`. Default `date = last_completed_session`. Idempotent.
3. **`compute_scores(market, date)` task.** Resolve universe → **read persisted `factor_values`** (`factor_values_for`) → `ScoreEngine.compute_scores` → `upsert_scores` → **emit `ScoresComputed{market, date, stocks}` after commit**. `run_job` `score:{market}:{date}`. Idempotent.
4. **Event chain + self-heal.** `on_indicators_computed → compute_factors.delay`; `on_factors_computed → compute_scores.delay`; both registered. `recompute_on_correction` resolves the stock's market and enqueues `compute_factors(market, current_session)` (fills the QV-027 seam → real self-heal).
5. **Boundaries.** Engines/read in `analytics`; the tasks + consumers in `jobs` (composition root). `analytics` imports no `jobs`. No migration; global tables → privileged engine.
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80 % coverage. **Unit:** engine split (compute_factor_values + compute_scores compose to the old compute_universe); consumers enqueue the right task; `FactorsComputed`/`ScoresComputed` only after persist. **Integration** (real Postgres, seeded universe): `compute_factors` persists `factor_values` + emits; `compute_scores` reads them back + persists `scores` + emits; idempotent re-runs; the recompute seam enqueues `compute_factors` for the market.

## Tasks / Subtasks

- [x] **Task 1 — split FactorEngine / ScoreEngine** (AC: #1)
  - [x] `analytics/scoring.py`: extract `FactorEngine.compute_factor_values(session, universe, as_of) -> dict[UUID, list[FactorValue]]` (the normalize half); refactor `ScoreEngine` to `compute_scores(factor_values, as_of) -> list[StockScore]` (blend half, was the per-stock aggregation + `_blend`); `compute_universe` = `ScoreEngine.compute_scores(FactorEngine.compute_factor_values(...))`. Update QV-029 unit tests to the new surface.
  - [x] `analytics/repositories.py`: `factor_values_for(session, stock_ids, date) -> dict[UUID, list[FactorValue]]` (read the persisted snapshot back).
- [x] **Task 2 — compute_factors + compute_scores tasks** (AC: #2, #3)
  - [x] `jobs/scoring.py` (new): `compute_factors(market, date_iso=None)` (`fac:{market}:{date}`, upsert factor_values, emit `FactorsComputed` post-commit) + `compute_scores(market, date_iso=None)` (`score:{market}:{date}`, read factor_values, upsert scores, emit `ScoresComputed` post-commit). Universe via `active_universe`. Add both to the mypy untyped-decorator override.
  - [x] `core/event_types.py`: `FactorsComputed` + `ScoresComputed` events (already stubbed? add/confirm `market, date, stocks`).
- [x] **Task 3 — event chain + self-heal fill** (AC: #4)
  - [x] `jobs/consumers.py`: `on_indicators_computed → compute_factors.delay(market, date)`; `on_factors_computed → compute_scores.delay(market, date)`; subscribe both in `register_pipeline_consumers`.
  - [x] `jobs/corrections.py`: `recompute_on_correction` resolves the stock's market (`stock_market` read) and enqueues `compute_factors(market, last_completed_session)` — the real self-heal (replaces the log stub). Keep `run_job` + the QV-027 tests green.
- [x] **Task 4 — tests + gates + reconcile** (AC: #6)
  - [x] Unit: engine-split composition; consumers enqueue; events post-persist. Integration (`tests/integration/test_scoring_jobs.py`): compute_factors → factor_values + FactorsComputed; compute_scores → scores + ScoresComputed; idempotent; recompute seam enqueues compute_factors. Run gates; reconcile QV-029 → done (already applied).

## Dev Notes

### The chain this completes (end-to-end, live)
```
PricesValidated → compute_indicators → IndicatorsComputed
                                     → compute_factors  (normalize → factor_values, commit) → FactorsComputed
                                     → compute_scores   (read snapshot → blend → scores, commit) → ScoresComputed
FundamentalsRevised → recompute_on_correction → compute_factors(market, today) → … → ScoresComputed   (self-heal)
```
Every event is a **durable persisted state**, emitted post-commit. `compute_scores` reads a committed `(market, date, model_version)` snapshot — never an in-memory milestone.

### Reuse map
- `ScoreEngine`/`Normalizer`/`FactorValue`/`StockScore`/`MODEL_VERSION` (QV-029); `upsert_scores`/`upsert_factor_values`; `stock_sectors`.
- `active_universe(session, index_code, market)` (universe resolution) + `last_completed_session` (default date) — QV-016/trading calendar.
- `run_job`/`run_key`/`JobResult`/`JobRunLedger`, `@app.task`, `get_event_bus()`, `register_pipeline_consumers` + thin-consumer pattern, patched `.delay` in tests — QV-015/024/025.
- `recompute_on_correction` (QV-027 seam) + `on_fundamentals_revised`; `IndicatorsComputed` payload (`market, date`).

### Boundaries & gates
- Engine split + `factor_values_for` in `analytics`; tasks + consumers in `jobs`. `analytics` imports no `jobs`/`api`; `lint-imports` 3/3. Add `quantvista.jobs.scoring` to the mypy untyped-decorator override. Coverage ≥ 80 % on the split + tasks + consumers.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (140 files) ·
  `lint-imports` 3 kept/0 broken (no `analytics → jobs`; `jobs` composition root imports both) ·
  `pytest` → **286 passed, 4 skipped** (Kafka broker down + 3 promtool). Coverage 94 %; new/changed:
  `jobs/scoring.py` 88 %, `jobs/consumers.py` **100 %**, `jobs/corrections.py` 89 %, `analytics/scoring.py`
  99 %, `analytics/repositories.py` 93 %.

### Completion Notes List

- **The scoring chain is now live end-to-end** — `PricesValidated → compute_indicators → IndicatorsComputed
  → compute_factors → FactorsComputed → compute_scores → ScoresComputed`, plus `FundamentalsRevised →
  recompute_on_correction → compute_factors(market, today) → … → ScoresComputed` (self-heal). Every event
  fires **post-commit** (durable state, never an in-memory milestone).
- **Engine split (owner-reviewed): factors canonical, scores projection.** `FactorEngine.compute_factor_values`
  (statistics — Polars normalization → the expensive `factor_values`) + `ScoreEngine.compute_scores(snapshot)`
  (business methodology — weighted blend, cheap, re-runnable) are **separate classes**; `compute_universe`
  composes them (QV-029 tests updated to the new surface, still green). `factor_values` is the shared
  artifact future consumers (score-v2, ESG, optimizer, ML) project — normalize once, project many.
- **`compute_factors`** (`jobs/scoring.py`): universe → `compute_factor_values` → `upsert_factor_values` →
  emit `FactorsComputed` **after the txn commits**. **`compute_scores`**: universe → `factor_values_for`
  (reads the committed snapshot back) → `compute_scores` → `upsert_scores` → emit `ScoresComputed`
  post-commit. Both `run_job` (`fac:` / `score:{market}:{date}`, `jobs_runs`), idempotent (integration
  re-run: row counts stable). Verified: compute_factors writes only `factor_values` (0 `scores`) + emits;
  compute_scores then writes `scores` + emits; composite ∈ [0,100].
- **Snapshot identity = `(market, date, model_version)` (v1):** `compute_scores` reads the snapshot in one
  transaction; post-commit event ordering means it only reads a committed snapshot. Consistency by
  construction (one `MODEL_VERSION` governs both engines). The `factor_snapshots` table + `universe_hash`
  + stored `normalization_version` check are tracked v2 infra (`scoring-methodology-roadmap`).
- **Self-heal filled** (`jobs/corrections.py`): `recompute_on_correction` resolves the stock's market
  (`stock_market`) and enqueues `compute_factors(market, last_completed_session)` — invalidate + recompute
  the factor *snapshot* (dataset-level), cascading to scores. Cross-sectional, so one stock's correction
  refreshes the universe. Historical-date re-score = future. QV-027's capstone + seam tests updated + green.
- **Boundaries:** engines + reads in `analytics`; tasks + consumers in `jobs`. `analytics` imports no
  `jobs`/`api`; `jobs` (composition root) imports both. **No migration; no security-reviewer** (internal
  compute/event wiring, no auth/PII/user-input). **Completes the core scoring trio (QV-028→029→030).**

### File List

**New**
- `backend/src/quantvista/jobs/scoring.py` — `compute_factors` + `compute_scores` tasks (post-commit events).
- `backend/tests/integration/test_scoring_jobs.py` — the two-stage pipeline + idempotency over real Postgres.

**Modified**
- `backend/src/quantvista/analytics/scoring.py` — split into `FactorEngine` + `ScoreEngine`; `compute_universe` composes them.
- `backend/src/quantvista/analytics/repositories.py` — `factor_values_for` (snapshot read); `upsert_factor_values` takes the snapshot dict.
- `backend/src/quantvista/market_data/repositories.py` — `stock_market` (self-heal market resolution).
- `backend/src/quantvista/jobs/consumers.py` — `on_indicators_computed` + `on_factors_computed` + subscriptions.
- `backend/src/quantvista/jobs/corrections.py` — `recompute_on_correction` enqueues `compute_factors` (self-heal fill).
- `backend/pyproject.toml` — mypy untyped-decorator override for `quantvista.jobs.scoring`.
- `backend/tests/test_pipeline_consumers.py`, `tests/test_score_engine.py`, `tests/integration/test_scoring.py`, `tests/integration/test_correction_pipeline.py` — updated to the split API + new edges.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-030 status; QV-029 → done (housekeeping).

### Change Log

- **2026-07-05 — QV-030 compute_factors + compute_scores jobs.** Split the QV-029 engine into
  **`FactorEngine`** (canonical `factor_values`) + **`ScoreEngine`** (score projection) and wired the two
  event-chained jobs: `compute_factors` persists the factor snapshot + emits `FactorsComputed`;
  `compute_scores` reads that committed snapshot back, blends it, persists `scores` + emits `ScoresComputed`
  — **events fire only post-commit**, both idempotent. Wired `IndicatorsComputed → compute_factors →
  FactorsComputed → compute_scores → ScoresComputed`, and **filled QV-027's `recompute_on_correction` seam**
  (a fundamentals correction recomputes the market's factor snapshot → scores, self-heal). Snapshot identity
  = `(market, date, model_version)`; `factor_snapshots` table + version-check tracked as v2. No migration.
  286 tests green, coverage 94 %; ruff/mypy-strict/import-linter clean. **Completes the QV-028→029→030 arc.**

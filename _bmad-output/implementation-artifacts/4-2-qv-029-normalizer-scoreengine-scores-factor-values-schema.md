---
baseline_commit: df1bf29b9279dc57942ba1709adc96a3767fc864
---

# Story 4.2: QV-029 — Normalizer + ScoreEngine + scores/factor_values schema

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a quant**,
I want **cross-sectional normalization and weighted composite scoring**,
so that **each stock gets explainable sub-scores + a composite, with the decomposition provably summing to the whole**.

> Canonical ID **QV-029** · Epic 4 (EPIC-INTEL) · `[QUANT]` · 8pts · Sprint 03 · depends: **QV-028 ✅** (factors), **QV-024 ✅** (events)
> Authoritative: `05` §1.2 (Normalizer / ScoreEngine / ScoreWeights / StockScore) · `05` §2 (default weights + missing-data policy). Consumes QV-028's `ALL_FACTORS`; the jobs are **QV-030**.

## ⚠️ Read first — the DDL already exists (verify, do NOT re-create)

`scores` and `factor_values` are already defined in **`0006_indicators_factors_scores.py`** (applied, partitioned monthly). **No migration.** `factor_values`: `stock_id, date, factor_key, raw_value, zscore, percentile_sector, percentile_universe`, `UNIQUE (stock_id, date, factor_key)`. `scores`: `stock_id, date, {fundamental,momentum,quality,sentiment,risk}_score, composite_score, ml_score (nullable), coverage, weights_version, model_version`, `UNIQUE (stock_id, date)`. QV-029's net code = the Normalizer + ScoreEngine + the two upserts.

## Locked decisions

- **Normalization (Polars-vectorized, per factor, cross-sectional; `05` §1.2 + robustness refinements):** direction-adjust the raw (`× direction`, so higher = better) → **winsorize the RAW to the sector's [p1, p99]** *(before* z — a few extreme filings distort mean/std; adopted over clip-the-z) → **z-score within sector** (`stocks.sector`; sample std; a sector with <2 stocks or σ=0 → neutral z=0) → **rank → 0–100 percentile**. A **non-finite raw (NaN/inf) → treated as `None`** (excluded; basic factor-quality guard). Store `raw_value` (actual raw), `zscore` (sector z of the winsorized, direction-adjusted value), `percentile_sector`, `percentile_universe`. The **`percentile_universe`** (0–100) is the factor's **normalized value** feeding the category score — the full per-factor audit trail (raw → z → percentile) is persisted, so the two-stage pipeline is reconstructable.
- **Category score = equal-weight mean of its factors' `percentile_universe`, over *available* factors** (v1). Missing factor (`None`) is excluded and the category re-normalizes over what's available (`05` §2). `05` §2's intra-category weights are a future refinement. A category with **no available factor → sub-score `NULL`** (e.g. sentiment, which has no concrete factor until Epic 5).
- **Composite = category weights blended, re-normalized over available (scored) categories.** Default **`ScoreWeights` v1 (`05` §2): fundamental 0.40, momentum 0.20, quality 0.20, sentiment 0.10, risk 0.10.** Categories with a `NULL` sub-score (sentiment now) are dropped and the remaining weights re-normalized to sum to 1 — so composite is always a clean 0–100 blend of what we actually scored.
- **Decomposition provably sums to composite.** `composite_score ≡ Σ (renormalized_weightᵢ × sub_scoreᵢ)` over scored categories — exact (to the `numeric(6,2)` rounding), **test-asserted**. `StockScore` carries the sub-scores + the per-category contribution decomposition so `04`'s API can prove parts-sum-to-whole.
- **Blend by the factor's QV-028 `category`** (PE/PB→fundamental, ROE/ROCE/DebtEquity→quality, Ret3M/6M/12M→momentum, Beta/Vol30D→risk). `coverage` = available_factors / total_factors × 100 (stored per stock).
- **Versioning — `model_version` is a whole-methodology fingerprint.** `weights_version = "v1"` (on `ScoreWeights`); **`model_version = "score-v1"` encodes the *entire* assumption set** — mean/std sector-z, winsorize-raw-[p1,p99], equal-weight intra-category, v1 category weights, missing-data re-normalize, sector grouping. **Any** methodology change (robust-z, industry norm, factor transforms, …) bumps `model_version` → historical scores stay reproducible with **zero schema change**. Both versions persisted on every `scores` row.
- **Deferred v2 methodology (tracked — `scoring-methodology-roadmap` memory):** robust z (median/MAD), factor transforms (earnings-yield/log-D-E), industry normalization (peer-count-gated), confidence + weighted coverage (need columns), time decay, learned weights (IC/ICIR), full factor-quality gates. Each drops in behind a bumped `model_version`. Not this story.
- **Placement:** `analytics/normalizer.py` + `analytics/scoring.py` + upserts in `analytics/repositories.py`. Reads via QV-028's `ScoringContext` (PIT). `analytics` imports `market_data` + `core`; global tables → privileged engine. **No migration.** Sentiment/ML columns stay `NULL` (their stories).

## Acceptance Criteria

1. **Schema conformance confirmed + documented.** Verify `0006` `scores` + `factor_values` (columns, `NUMERIC`, uniqueness, monthly partitioning). Record in the Dev Agent Record. **No duplicate migration.**
2. **`Normalizer`.** `normalize(values: dict[UUID, float | None], sectors: dict[UUID, str | None], direction: int) -> dict[UUID, NormResult]` — direction-adjust → **winsorize raw to sector [p1,p99]** → sector z-score → 0–100 `percentile_sector` + `percentile_universe` (higher = better). `None` **and non-finite** inputs excluded; σ=0 / singleton sector → neutral. Polars-vectorized.
3. **`ScoreEngine.compute_universe(session, universe, as_of) -> list[StockScore]`.** Compute raw factors for all stocks via the PIT `ScoringContext`; normalize per factor; equal-weight → category sub-scores (excluding missing); re-normalized weighted composite; `coverage`. Returns `StockScore` (sub-scores, composite, coverage, per-factor `factor_values`, decomposition). **Decomposition sums to composite.** `weights_version`/`model_version` set.
4. **Persistence.** `upsert_factor_values` (per stock×factor: raw/z/percentiles, `ON CONFLICT (stock_id, date, factor_key)`) + `upsert_scores` (per stock: sub-scores/composite/coverage/versions, `ON CONFLICT (stock_id, date)`). Idempotent; global → privileged engine.
5. **Missing-data policy + coverage.** A factor returning `None` is excluded, its category re-normalized; a fully-missing category → `NULL` sub-score, its weight re-normalized out of the composite; `coverage` reflects available/total.
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80 % coverage. **Unit:** Normalizer (known sector-z/percentile, direction flip, σ=0 neutral, None excluded); ScoreEngine on a crafted universe (category blend, **decomposition == composite**, missing-factor re-normalize + coverage, sentiment→NULL + weight redistribution). **Integration** (real Postgres, seeded universe with sectors + fundamentals + indicators): `compute_universe` persists `scores` + `factor_values`, composite in [0,100], decomposition sums, idempotent re-run.

## Tasks / Subtasks

- [x] **Task 1 — verify schema conformance** (AC: #1)
  - [x] Read `0006` `scores` + `factor_values` vs `03` §4.1 / `05` §1.2; conformance note; confirm **no** migration.
- [x] **Task 2 — Normalizer** (AC: #2)
  - [x] `analytics/normalizer.py`: `NormResult` (zscore, percentile_sector, percentile_universe); `Normalizer.normalize(...)` — Polars sector z → winsorize ±3 → percentile, direction-adjusted; None/σ=0 handling. Unit test.
- [x] **Task 3 — ScoreWeights + ScoreEngine** (AC: #3, #5)
  - [x] `analytics/scoring.py`: `ScoreWeights` (default v1), `FactorValue` + `StockScore` dataclasses, `ScoreEngine(factors, normalizer, weights)`; `compute_universe(session, universe, as_of)` — raw via `ScoringContext`, normalize, category blend (equal-weight, missing excluded), re-normalized composite, coverage, decomposition. `MODEL_VERSION = "score-v1"`.
- [x] **Task 4 — persistence** (AC: #4)
  - [x] `analytics/repositories.py`: `upsert_factor_values` + `upsert_scores` (`ON CONFLICT … DO UPDATE`).
- [x] **Task 5 — tests + gates + reconcile** (AC: #6)
  - [x] `tests/test_normalizer.py` + `tests/test_score_engine.py` (crafted universe; **decomposition == composite**; missing/coverage; sentiment NULL). `tests/integration/test_scoring.py` (real PG: persist + idempotent + invariants). Run gates; reconcile QV-028 → done (already applied).

## Dev Notes

### Scope discipline
QV-029 = verify the `scores`/`factor_values` schema + the Normalizer + ScoreEngine + the two upserts. **Not this story:** the `compute_factors`/`compute_scores` **jobs** (→ **QV-030**, which call this engine and fill QV-027's `recompute_on_correction` seam); sentiment scoring (→ Epic 5, column stays `NULL`); the ML `ml_score` (→ `06`/`12`, `NULL`); user-customizable weights on the Quant tier (later — `ScoreWeights` is already versioned for it); the `04` score API. **No migration.**

### Scoring pipeline (the invariant that matters)
```
raw factor (PIT, QV-028) ──×direction──▶ winsorize raw [p1,p99] ──▶ sector z-score ──▶ 0–100 pct
                                                                              │  (per factor)
   category sub-score = mean(percentile_universe over available factors) ◀────┘
   composite = Σ_over_scored_categories( weightᵢ / Σweights_scored · sub_scoreᵢ )   ← == decomposition
   coverage  = available_factors / total_factors · 100
```
A category with no available factor → `NULL` sub-score → dropped from the weighted blend (weights re-normalized). This makes `composite == Σ contributions` hold **exactly**, and keeps composite a clean 0–100 even while sentiment/ML are absent.

### Reuse map
- `ScoringContext` + `ALL_FACTORS` + `Factor.direction`/`category`/`key` — QV-028 (PIT reads, bias-free).
- `stocks.sector` (`0003`, indexed) — the sector grouping for z-score; query per universe.
- Polars (QV-025 dep) — vectorized normalization across the universe.
- Upsert template (`ON CONFLICT … DO UPDATE`) — `upsert_daily_prices`/`upsert_technical_indicators`.
- Seed scaffold (throwaway market + stocks **with sectors** + `fundamentals` + `technical_indicators`) — `test_factor_pit.py` + `test_compute_indicators.py`.

### Boundaries & gates
- `analytics/normalizer.py` imports Polars + stdlib; `analytics/scoring.py` imports factors/context/normalizer/repositories; `analytics/repositories.py` imports `core` + SQLAlchemy. `analytics` imports `market_data` (allowed); imports no `jobs`/`api`. `lint-imports` 3/3. Coverage ≥ 80 % on normalizer + engine + upserts.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (138 files) ·
  `lint-imports` 3 kept/0 broken (`analytics → market_data` allowed) · `pytest` → **282 passed, 4 skipped**
  (Kafka broker down + 3 promtool). Coverage 94 %; new: `analytics/normalizer.py` **100 %**,
  `analytics/scoring.py` **99 %**, `analytics/repositories.py` 89 %.
- **RED confirmed** first: `test_normalizer.py` failed with `ModuleNotFoundError: quantvista.analytics.normalizer`.

### Completion Notes List — Task 1 schema conformance (`0006`)

**`scores` + `factor_values` conform — NO migration.** `factor_values`: `stock_id, date, factor_key,
raw_value, zscore, percentile_sector, percentile_universe`, `UNIQUE (stock_id, date, factor_key)`, monthly
partitioned. `scores`: `{fundamental,momentum,quality,sentiment,risk}_score, composite_score, ml_score
(nullable), coverage, weights_version, model_version`, `UNIQUE (stock_id, date)`, monthly partitioned,
index `(date, composite_score DESC)`. Matches `03` §4.1 / `05` §1.2. No deviation.

### Completion Notes List — implementation

- **`Normalizer`** (`analytics/normalizer.py`, 100 %): Polars per-factor — direction-adjust →
  **winsorize the raw to sector [p1,p99]** (before z; adopted from the review over clip-the-z) → sector
  z-score (sample std; σ=0 / singleton → neutral 0) → 0–100 `percentile_sector` (within sector) +
  `percentile_universe` (of the sector-z). None **and non-finite (NaN/inf)** excluded. Unit-pinned on a
  crafted universe (z ∓0.707, direction flip, σ=0 neutral, exclusion).
- **`ScoreEngine`** (`analytics/scoring.py`, 99 %): `compute_universe` (pure — reads only) computes raw
  factors via QV-028's PIT `ScoringContext`, normalizes each, **equal-weight category** sub-scores over
  available factors, composite = category weights (**v1: .40/.20/.20/.10/.10**) **re-normalized over
  scored categories** (sentiment drops → weight redistributes), `coverage`. `StockScore` carries the
  decomposition; **`composite ≡ Σ contributions`** — asserted at the object level (unit) *and* on
  persisted rows (integration, `abs=0.01`). `MODEL_VERSION="score-v1"` = the methodology fingerprint.
- **Persistence** (`analytics/repositories.py`, 89 %): `upsert_scores` (`ON CONFLICT (stock_id, date)`) +
  `upsert_factor_values` (`ON CONFLICT (stock_id, date, factor_key)`) — the full audit trail (raw → z →
  percentiles per factor + sub-scores/composite/coverage/versions per stock). Idempotent (integration
  re-run: row counts stable). Global tables → privileged engine.
- **Look-ahead safe** — scoring reads only through the QV-028 `ScoringContext`, so PIT correctness is
  inherited. **No migration; no security-reviewer** (read-only analytics, no auth/PII/user-input).
- **Adopted from the QV-029 methodology review (owner-confirmed):** winsorize-raw-first, non-finite guard,
  and `model_version` as a whole-methodology fingerprint. The heavier v2 upgrades (robust-z, industry norm,
  factor transforms, confidence, time-decay, learned weights) are tracked in the `scoring-methodology-roadmap`
  memory, each droppable behind a bumped `model_version`.

### File List

**New**
- `backend/src/quantvista/analytics/normalizer.py` — cross-sectional `Normalizer` (Polars).
- `backend/src/quantvista/analytics/scoring.py` — `ScoreWeights`, `FactorValue`, `StockScore`, `ScoreEngine`.
- `backend/tests/test_normalizer.py` — normalizer unit (known z/percentile, direction, σ=0, exclusion).
- `backend/tests/test_score_engine.py` — blend invariant + category aggregation (unit, fake factors).
- `backend/tests/integration/test_scoring.py` — compute + persist + decomposition==composite over real Postgres.

**Modified**
- `backend/src/quantvista/analytics/repositories.py` — `upsert_scores` + `upsert_factor_values`.
- `backend/src/quantvista/market_data/repositories.py` — `stock_sectors` (peer grouping read).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-029 status; QV-028 → done (housekeeping).

### Change Log

- **2026-07-05 — QV-029 Normalizer + ScoreEngine + scores/factor_values.** Verified the `0006`
  `scores`/`factor_values` schema (no migration) and shipped score-v1: a Polars `Normalizer`
  (direction-adjust → winsorize-raw-[p1,p99] → sector z → 0–100 percentiles) + a `ScoreEngine` that
  blends QV-028's factors into equal-weight category sub-scores and a **re-normalized weighted composite**
  whose **decomposition provably sums to the composite** (asserted in-memory + on persisted rows), with
  `coverage` and the two upserts. `model_version="score-v1"` fingerprints the whole methodology; the
  review's robustness refinements (winsorize-raw, finite-guard) are in, heavier v2 upgrades tracked in a
  memory. No migration. 282 tests green, coverage 94 % (normalizer 100 %, scoring 99 %);
  ruff/mypy-strict/import-linter clean.

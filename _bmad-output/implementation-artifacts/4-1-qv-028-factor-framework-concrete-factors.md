---
baseline_commit: dd7ad524bf7094c3504a93699fe52d1e0bc9a861
---

# Story 4.1: QV-028 — Factor framework + concrete factors

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a quant**,
I want **pluggable factors that read only point-in-time data through a context**,
so that **the scoring engine is extensible (Open/Closed) and structurally free of look-ahead bias**.

> Canonical ID **QV-028** · Epic 4 (EPIC-INTEL) · `[QUANT]` · 8pts · Sprint 03 (**first story**) · depends: **QV-025 ✅** (technical_indicators), **QV-021 ✅** (bitemporal fundamentals)
> Authoritative: `05` §1.1 (`Factor` ABC + `ScoringContext`) · `05` §2 (default factor set + categories). First Epic-4 story — the scoring engine (QV-029) + jobs (QV-030) build on this.

## What this story is (and is NOT)

QV-028 = the **factor abstractions + concrete factors + the PIT `ScoringContext`** + the leakage/None proofs. **NOT this story:** the `Normalizer`/`ScoreEngine`/`scores`+`factor_values` persistence (→ **QV-029**), the `compute_factors`/`compute_scores` jobs (→ **QV-030**, which fill QV-027's `recompute_on_correction` seam), sentiment factors (need news data → **Epic 5**). **No migration.**

## Locked decisions

- **`Factor` ABC per `05` §1.1** — `key: str`, `category: FactorCategory`, `direction: int` (+1 higher-is-better, −1 lower-is-better), `compute(ctx: ScoringContext, stock_id: UUID, as_of: date) -> float | None`. Matches the existing `analytics.interfaces.IFactor` Protocol. Returns `None` when the input is unavailable (excluded downstream, `05` §2 missing-data policy).
- **Factors read ONLY through `ScoringContext` (structural look-ahead defense).** The context exposes **PIT reads only** — `fundamentals_as_of(stock_id, as_of)`, `indicator_as_of(stock_id, as_of)`, `universe()` — and factors receive *only* the context (no `Session`, no repo, no "latest" query). "A factor cannot read latest data directly" is therefore enforced **by construction**, then proven by a leakage test (AC #3). `05` §1.1.
- **`as_of` (a date) → knowledge-time = end of the `as_of` day** for the bitemporal fundamentals read (`fundamentals_as_of` takes a `datetime`). A restatement whose `knowledge_from` is *after* `as_of` is invisible — this is the QV-021 PIT guarantee applied to scoring.
- **Concrete factor set (from available PIT data; `05` §2):** **PE**, **PB** (FUNDAMENTAL, dir −1) · **ROE**, **ROCE** (QUALITY, +1), **DebtEquity** (QUALITY, −1) · **Ret3M**, **Ret6M**, **Ret12M** (MOMENTUM, +1) · **Beta**, **Vol30D** (RISK, −1). Fundamental/quality read `fundamentals_as_of().ratios[...]`; momentum/risk read `indicator_as_of()[...]`. **`SENTIMENT` stays in the category enum but has no concrete factor** — needs news data (Epic 5); the AC's factor list is fundamental/momentum/quality/risk only.
- **New PIT read `technical_indicators_as_of(session, stock_id, as_of)`** — the latest `technical_indicators` row with `date <= as_of` (indicators are `(stock_id, date)`-keyed, not bitemporal; "PIT" = no future-dated row). Lives in `market_data` (where the table lives).
- **Placement:** `analytics/factors.py` + `analytics/context.py`; `analytics` imports `market_data` (the DAG allows higher→lower — contract 1). No new dependency, no migration, global tables → privileged/read session.

## Acceptance Criteria

1. **`Factor` ABC + `FactorCategory` + concrete factors.** `FactorCategory` (FUNDAMENTAL/MOMENTUM/QUALITY/SENTIMENT/RISK). `Factor` ABC as above. The 10 concrete factors (PE/PB/ROE/ROCE/DebtEquity/Ret3M/Ret6M/Ret12M/Beta/Vol30D) each with the right `key`/`category`/`direction`, computing via the PIT context and returning `None` when the ratio/indicator is missing. An `ALL_FACTORS` registry exposes them for QV-029.
2. **`ScoringContext` (PIT-only).** `fundamentals_as_of(stock_id, as_of)` (bitemporal, end-of-`as_of`-day knowledge-time), `indicator_as_of(stock_id, as_of)` (latest row `date <= as_of`), `universe()`. Backed by `fundamentals_as_of` (QV-021) + the new `technical_indicators_as_of`. No method returns future data.
3. **No look-ahead (leakage test + None policy).** Prove: a fundamental **restated at a later knowledge-time** and an indicator row **dated after `as_of`** are BOTH invisible at `as_of` (factors return the earlier-known value, not the future one); a factor returns `None` when its input is absent. This is the structural bias defense `05` §1.1 requires.
4. **Boundaries.** Factors/context in `analytics` (imports `market_data` PIT repos only); `market_data` stays a leaf; `analytics` imports no `jobs`/`api`. `lint-imports` green. No migration; global tables → privileged/read session.
5. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80 % coverage on new code. **Unit** (fake context): each factor's `key`/`category`/`direction` + reads the right field + `None` on missing. **Integration** (real Postgres): the `ScoringContext` PIT reads + the **leakage test** (bitemporal restatement + future-dated indicator both excluded at `as_of`).

## Tasks / Subtasks

- [x] **Task 1 — PIT indicator read** (AC: #2, #4)
  - [x] `market_data/repositories.py`: `technical_indicators_as_of(session, stock_id, as_of) -> Mapping[str, Decimal | None] | None` — the indicator row with the greatest `date <= as_of` (the 14 indicator columns), else `None`.
- [x] **Task 2 — `ScoringContext`** (AC: #2)
  - [x] `analytics/context.py` (new): `ScoringContext(session, as_of, universe)`; `fundamentals_as_of(stock_id, as_of)` (→ `fundamentals_as_of` at end-of-day knowledge-time), `indicator_as_of(stock_id, as_of)` (→ `technical_indicators_as_of`), `universe()`. PIT reads only.
- [x] **Task 3 — `Factor` ABC + concrete factors** (AC: #1)
  - [x] `analytics/factors.py` (new): `FactorCategory`, `Factor` ABC, `_FundamentalFactor`/`_IndicatorFactor` DRY bases, the 10 concrete factors, `ALL_FACTORS`. Each `compute` reads via the context, `float | None`.
- [x] **Task 4 — tests** (AC: #3, #5)
  - [x] `tests/test_factors.py`: fake-context unit tests — each factor's metadata + reads-right-field + `None`-on-missing; `ALL_FACTORS` covers the 4 categories.
  - [x] `tests/integration/test_factor_pit.py`: seed a stock with a bitemporal restatement (T_early pe=10, T_late pe=12) + indicator rows dated before/after `as_of`; assert `PEFactor` at `as_of` (between the two knowledge-times) returns 10 (not 12) and `Return6MFactor` reads the ≤`as_of` row (not the future one); `None` when no data. Cleanup by ids.
  - [x] Run all gates; reconcile QV-027 → done (already applied on this branch).

## Dev Notes

### Data sources (what each factor reads, PIT)
- **Fundamentals** (`fundamentals_as_of`, QV-021 bitemporal) → `ratios`: `pe, forward_pe, pb, roe, roce, debt_equity`. Factors: PE, PB, ROE, ROCE, DebtEquity.
- **Indicators** (`technical_indicators_as_of`, new; QV-025 table) → `ret_3m/6m/12m, beta_1y, vol_30d` (+ sma/ema/rsi/macd/bollinger/atr available). Factors: Ret3M/6M/12M, Beta, Vol30D.
- **Universe** — the constituent set at `as_of` (constructed by the caller / QV-030; for QV-028 the context just holds it).

### The look-ahead defense (why this matters)
Scoring on data that wasn't knowable at `as_of` fabricates backtest performance. Two leak paths, both closed here: (1) **fundamentals** — a Q3 restatement filed in Nov must not affect an Oct score → the bitemporal `knowledge_from <= end-of-as_of-day` filter (QV-021); (2) **indicators** — a row dated after `as_of` must not be read → `date <= as_of`. Factors physically cannot bypass these because they only hold a `ScoringContext`. The integration test *proves* both.

### Reuse map
- `fundamentals_as_of(session, stock_id, as_of: datetime, statement_type=…)` + `FundamentalVersion.ratios` — QV-021.
- `technical_indicators` (QV-025) + its columns; add the `_as_of` read alongside `price_history_for_indicators`.
- `analytics.interfaces.IFactor` (already present) — the `Factor` ABC conforms.
- Seed scaffold (throwaway market+stock, `record_fundamental_version` at T_early/T_late, `technical_indicators` inserts) — from `test_fundamentals.py` + `test_compute_indicators.py`.

### Boundaries & gates
- `analytics/factors.py` + `analytics/context.py` import `market_data` (fundamentals + repositories) + `core` + stdlib — allowed (analytics is above market_data). `market_data` unchanged as a leaf. `analytics` imports no `jobs`/`api`. `lint-imports` 3/3. Coverage ≥ 80 % on factors + context + the new read.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (133 files) ·
  `lint-imports` 3 kept/0 broken (`analytics → market_data` allowed by the layered DAG; `market_data`
  unchanged as a leaf) · `pytest` → **272 passed, 4 skipped** (Kafka broker down + 3 promtool).
  Coverage 94 %; new: `analytics/factors.py` **100 %**, `analytics/context.py` 95 %.

### Completion Notes List

- **Look-ahead bias closed by construction + proven.** Factors hold *only* a `ScoringContext` (no
  `Session`/repo), so "read latest directly" is impossible. The integration leakage test proves both
  leak paths shut: at `as_of` = 2026-01-20, a fundamental **restated at a later knowledge-time**
  (pe 12 known 2026-02-10) is invisible → `PEFactor` returns **10**, and a **future-dated** indicator
  row (2026-03-01) is invisible → `Return6MFactor` reads the ≤`as_of` row (0.05). After the restatement's
  knowledge-time (`as_of` = 2026-02-15), `PEFactor` returns **12** — the correction becomes visible
  exactly when it was known. `05` §1.1.
- **`Factor` ABC + 10 concrete factors** (`analytics/factors.py`, 100 %): two DRY bases —
  `_FundamentalFactor` (reads `ratios[...]`) + `_IndicatorFactor` (reads the indicator column) — and
  PE/PB (fundamental), ROE/ROCE/DebtEquity (quality), Ret3M/6M/12M (momentum), Beta/Vol30D (risk).
  Each returns `None` when its source or field is missing (`05` §2 missing-data policy). `ALL_FACTORS`
  registry feeds QV-029. `SENTIMENT` is in the enum but has no concrete factor (news → Epic 5).
- **`ScoringContext`** (`analytics/context.py`, 95 %): PIT-only reads — `fundamentals_as_of`
  (bitemporal, knowledge-time = end of the `as_of` day), `indicator_as_of` (latest row `date <= as_of`),
  `universe()`. Conforms to `analytics.interfaces.IFactor`'s `ctx` role.
- **`technical_indicators_as_of`** (`market_data/repositories.py`): the greatest-`date ≤ as_of` indicator
  row (no future row) — the indicator PIT primitive, mirroring the bitemporal fundamentals read.
- **Boundaries:** `analytics` imports `market_data` (allowed — higher layer); `market_data` stays a leaf;
  `analytics` imports no `jobs`/`api`. **No migration; no security-reviewer** (read-only analytics, no
  auth/PII/user-input).

### File List

**New**
- `backend/src/quantvista/analytics/factors.py` — `FactorCategory`, `Factor` ABC + 2 DRY bases, 10 concrete factors, `ALL_FACTORS`.
- `backend/src/quantvista/analytics/context.py` — `ScoringContext` (PIT-only gateway).
- `backend/tests/test_factors.py` — factor metadata + reads + None policy (unit, fake context).
- `backend/tests/integration/test_factor_pit.py` — the look-ahead leakage proof (real Postgres).

**Modified**
- `backend/src/quantvista/market_data/repositories.py` — `technical_indicators_as_of` PIT read.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-028 status; QV-027 → done + epic-4 in-progress (housekeeping).

### Change Log

- **2026-07-05 — QV-028 factor framework + concrete factors.** First Epic-4 story: a pluggable,
  PIT-only `Factor` ABC + 10 concrete factors (PE/PB/ROE/ROCE/DebtEquity/Ret3M/6M/12M/Beta/Vol30D)
  reading through a `ScoringContext` that exposes only bitemporal fundamentals (`fundamentals_as_of`)
  + `date ≤ as_of` indicators (`technical_indicators_as_of`). Look-ahead bias is impossible by
  construction (factors hold only the context) and **proven** by a real-Postgres leakage test (a later
  restatement + a future-dated indicator are both invisible at `as_of`). `ALL_FACTORS` feeds QV-029's
  ScoreEngine. No migration. 272 tests green, coverage 94 % (factors 100 %); ruff/mypy-strict/import-linter clean.

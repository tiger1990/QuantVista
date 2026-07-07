---
baseline_commit: 2e402f3dbf9a81efcfda6c5ad734c08bf85fee57
---

# Story 4.6: QV-033 — API: /scores/{symbol} + /decomposition + /rankings

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **an analyst**,
I want **a stock's scores, their factor decomposition, and a ranked leaderboard**,
so that **I can trust the score (parts provably sum to the whole) and rank the universe**.

> Canonical ID **QV-033** · Epic 4 (EPIC-INTEL) · `[BE]` · 5pts · Sprint 03 · depends: **QV-031 ✅** (cache), **QV-007 ✅** (auth/entitlement)
> Authoritative: `04` §3.3 (`/scores/{symbol}`, `/scores/{symbol}/decomposition`, `/rankings`; decomposition **sums to composite** with PIT dates — US-02 AC; `/rankings` Free-tier truncated to top-50). Builds on QV-032's read surface.

## What exists (reuse)

- **`Envelope`**, `get_current_principal`, `get_global_session` (no-RLS global read), `get_entitlement_service`, `ERROR_STATUS` (`not_found`), the disclaimer helper — QV-032/007.
- **`scores` + `factor_values`** (QV-029); `rankings_for` + `cached_rankings` (QV-029/031); `ALL_FACTORS` + `DEFAULT_WEIGHTS` + the blend logic (QV-029). **No migration.**
- **Entitlement quota** `universe_scores_top` (Free = 50, paid = NULL/unlimited) via `EntitlementService.limit(tenant_id, key)`.

## Locked decisions

- **`GET /scores/{symbol}?as_of=`** (auth) — returns `{symbol, as_of, fundamental, momentum, quality, sentiment, risk, composite, coverage, weights_version, model_version, disclaimer}`. `as_of` optional → the **latest score with `date <= as_of`** (PIT); omitted → the latest score. `not_found` (404) if the stock has no score. Not entitlement-gated (single-stock read).
- **`GET /scores/{symbol}/decomposition?as_of=`** (auth) — proves **Σ contributions == composite** (US-02). Reproduces the ScoreEngine blend from the persisted `factor_values`: per factor, `contribution = (renorm_weight[category] / count[category]) × percentile_universe`, where `renorm_weight` re-normalizes `DEFAULT_WEIGHTS` over the **scored** categories and `count` is factors-per-category — so `Σ = composite` exactly (to `numeric` rounding). Each factor row: `factor_key, category, raw_value, zscore, percentile_sector, percentile_universe, contribution`, plus the **PIT `as_of`** (the score date). Deeper per-input lineage (which filing/indicator date fed each factor) is **QV-073's raw-capture** — noted.
- **`GET /rankings?universe=NIFTY200&market=NSE&as_of=&limit=50`** (auth + **entitlement quota**) — composite-desc leaderboard over the market's scored stocks (dev: NIFTY200 = NSE). **Bounded top-N, NOT cursor-paginated** (`04` shows `limit=50` capped by entitlement — a leaderboard, not a deep list). **`cached_rankings`** returns the full ranked list (cached under `rank:{market}:{date}`, invalidated on `ScoresComputed`); the endpoint truncates to **`min(requested_limit, entitlement_limit)`** — Free `universe_scores_top=50` → top-50; paid unlimited → up to `limit`. `meta` carries `{as_of, tier_limit, truncated}` + disclaimer.
- **`as_of` resolution** — a small `latest_score_date(session, *, market, on_or_before)` picks the newest `scores.date` (≤ `as_of` if given) for the universe; per-symbol reads use `date <= as_of`. Keeps everything PIT-correct.
- **Placement:** routes in `api/routes_scores.py`; read-models `score_of` + `latest_score_date` in `analytics/repositories.py`; the `decompose` computation in `analytics/services.py` (reuses factor→category map + weights); Pydantic DTOs in `schemas/scores.py`. **No migration.**

## Acceptance Criteria

1. **`/scores/{symbol}`** — auth; optional `as_of`; returns the latest (or ≤ as_of) score with sub-scores/composite/coverage/versions + disclaimer header + `meta.disclaimer`; 404 `not_found` if unscored.
2. **`/scores/{symbol}/decomposition`** — auth; per-factor contributions from `factor_values`; **Σ contributions == composite** (asserted in a test, `abs<=0.01`); each factor carries raw/z/percentiles + `contribution` + the PIT `as_of`; 404 if unscored; disclaimer set.
3. **`/rankings`** — auth; composite-desc; **Free tier truncated to top-50** (`universe_scores_top`), paid up to `limit`; served from `cached_rankings`; `meta` = `{as_of, tier_limit, truncated, disclaimer}`.
4. **Read-models + decompose.** `score_of(session, symbol, as_of)` + `latest_score_date(...)` in `analytics/repositories.py`; `decompose(session, symbol, as_of) -> dict | None` in `analytics/services.py` (contributions sum to composite).
5. **Boundaries + errors.** Routes in `api`; reads in `analytics`; DTOs in `schemas`. Global reads via `get_global_session`; entitlement via `EntitlementService` (tenant). Envelope errors (`not_found` 404, unauth 401). `lint-imports` green. **No migration.**
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80 % coverage. **Unit:** `decompose` sums to composite on a crafted snapshot; the entitlement truncation (min(limit, tier)). **Integration** (real PG + Redis via `TestClient` + auth): `/scores/{symbol}` (latest + `as_of`, 404, disclaimer); `/scores/{symbol}/decomposition` (**Σ == composite**, PIT `as_of` present); `/rankings` (composite-desc order; **Free capped to 50** vs a paid tenant seeing more; `truncated` flag).

## Tasks / Subtasks

- [x] **Task 1 — schemas + read-models** (AC: #1, #4)
  - [x] `schemas/scores.py`: `ScoreResponse`, `FactorContribution`, `DecompositionResponse`, `RankingItem`. `analytics/repositories.py`: `score_of(session, symbol, as_of=None)` (latest score ≤ as_of, `None` if none) + `latest_score_date(session, *, market, on_or_before=None)`.
- [x] **Task 2 — decompose** (AC: #2, #4)
  - [x] `analytics/services.py`: `decompose(session, symbol, as_of=None)` — read `score_of` + `factor_values_for`; group by category (from `ALL_FACTORS`); contribution = `(renorm_weight[cat]/count[cat]) × percentile_universe`; return factors + composite (Σ contributions == score composite). `None` if unscored.
- [x] **Task 3 — routes** (AC: #1, #2, #3, #5)
  - [x] `api/routes_scores.py`: `GET /scores/{symbol}`, `GET /scores/{symbol}/decomposition`, `GET /rankings`. Auth; disclaimer; `/rankings` = `cached_rankings` truncated to `min(limit, EntitlementService.limit(tenant, "universe_scores_top") or limit)`; 404 on unscored. Register in `app.py`.
- [x] **Task 4 — tests + gates + reconcile** (AC: #6)
  - [x] `tests/test_decompose.py` (unit: Σ==composite; entitlement truncation helper) + `tests/integration/test_api_scores.py` (TestClient + real PG + auth: scores latest/as_of/404, decomposition Σ==composite + PIT as_of, rankings order + Free-vs-paid cap). Run gates; reconcile QV-032 → done (already applied).

## Dev Notes

### Decomposition math (parts sum to composite)
```
composite = Σ_cat  renorm_w[cat] · subscore[cat]                     (ScoreEngine, QV-029)
          = Σ_cat  renorm_w[cat] · mean(percentile_universe over cat's factors)
          = Σ_factor  (renorm_w[cat(f)] / count[cat(f)]) · percentile_universe[f]   ← per-factor contribution
```
`renorm_w` = `DEFAULT_WEIGHTS` re-normalized over the categories actually present (sentiment absent → dropped), matching how the persisted composite was formed. Test asserts `Σ contributions == scores.composite_score` (± rounding).

### Reuse map
- `factor_values_for` (QV-030) → the per-factor snapshot; `ALL_FACTORS` (key→category) + `DEFAULT_WEIGHTS` + `ScoreEngine._blend` weight logic (QV-029).
- `cached_rankings` + `rankings_for` (QV-029/031) for `/rankings`; `EntitlementService.limit` (QV-007) for the tier cap.
- `Envelope`, `get_current_principal`, `get_global_session`, `get_entitlement_service`, disclaimer helper, `StockNotFound`/`ERROR_STATUS` — QV-032.
- Integration scaffold (seed market+stocks+scores+factor_values, register→bearer) — mirror `test_api_stocks.py`; a paid tenant via a subscription row / plan for the entitlement test.

### Boundaries & gates
- Routes in `api` (composition root); `score_of`/`latest_score_date` + `decompose` in `analytics`; DTOs in `schemas` (Pydantic leaf). Global reads via `get_global_session`; entitlement reads its own RLS session. `lint-imports` 3/3. Coverage ≥ 80 % on decompose + routes. **Not this story:** `/screener` (QV-later), news/sentiment scores (Epic 5), per-input factor lineage (QV-073), the frontend (QV-035).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Verified against local **PostgreSQL 18.4** + native Redis (via `create_app()` `TestClient`).
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (152 files) ·
  `lint-imports` 3 kept/0 broken · `pytest` → **306 passed, 4 skipped**. Coverage 95 %; new:
  `api/routes_scores.py` 96 %, `analytics/services.py` 98 %, `schemas/scores.py` **100 %**,
  `analytics/repositories.py` 96 %.
- Note: this FastAPI version lazy-includes routers (`_IncludedRouter`), so `app.routes` doesn't list
  them until request time — the routing is verified via the `TestClient` integration tests, not introspection.

### Completion Notes List

- **The scores are now explainable + rankable over HTTP** — `/scores/{symbol}`, `/scores/{symbol}/
  decomposition`, `/rankings`. Analysts can pull a score, prove *why* (parts sum to whole), and rank the
  universe.
- **`GET /scores/{symbol}`** (auth) — composite + 5 sub-scores + coverage + versions + disclaimer; `as_of`
  optional → latest score `≤ as_of` (PIT); 404 if unscored.
- **`GET /scores/{symbol}/decomposition`** — the US-02 proof: per-factor `contribution =
  (renorm_weight[cat]/count[cat]) × percentile_universe`, reproducing the ScoreEngine blend from the
  persisted `factor_values`. **Integration-tested that `Σ contributions == composite`** on real data (seeded
  via the *actual* `ScoreEngine.compute_scores`, so score + factor_values are internally consistent), each
  factor carrying its PIT `as_of`. Deeper per-input lineage → QV-073.
- **`GET /rankings`** — composite-desc leaderboard from `cached_rankings` (QV-031), **truncated to the
  tenant's `universe_scores_top` quota** (Free = 50, paid = unlimited) via `EntitlementService.limit`; a
  bounded top-N (not cursor-paginated). `meta` surfaces `{as_of, tier_limit, truncated, universe}`. The cap
  is a pure `effective_limit(requested, tier)` helper (unit-tested); the endpoint proves it end-to-end
  (`tier_limit=50` surfaced, `limit=1` → `truncated=true`).
- **Read-models** `score_of`/`latest_score_date` (`analytics/repositories.py`) on `get_global_session`;
  `decompose` (`analytics/services.py`). Pydantic DTOs in `schemas/scores.py`. `as_of` resolution keeps
  everything PIT-correct. **No migration; no security-reviewer** beyond auth (read-only score data).
  **Not this story:** `/screener`, sentiment/ML scores (Epic 5/ML), per-input factor lineage (QV-073), the
  frontend (QV-035).

### File List

**New**
- `backend/src/quantvista/schemas/scores.py` — `ScoreResponse`, `FactorContribution`, `DecompositionResponse`, `RankingItem`.
- `backend/src/quantvista/api/routes_scores.py` — the 3 endpoints + `effective_limit` quota helper.
- `backend/tests/test_scores_logic.py` — `effective_limit` (unit).
- `backend/tests/integration/test_api_scores.py` — scores/decomposition(Σ==composite)/rankings e2e (TestClient + real PG + auth).

**Modified**
- `backend/src/quantvista/analytics/repositories.py` — `score_of` + `latest_score_date` reads.
- `backend/src/quantvista/analytics/services.py` — `decompose` (contributions sum to composite).
- `backend/src/quantvista/api/app.py` — register `scores_router`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-033 status; QV-032 → done (housekeeping).

### Change Log

- **2026-07-08 — QV-033 API: /scores/{symbol} + /decomposition + /rankings.** The explainability + ranking
  endpoints: a stock's composite + sub-scores (`as_of`-aware, PIT), a factor **decomposition that provably
  sums to the composite** (US-02 — `contribution = renorm_weight/count × percentile_universe`, integration-
  proven on ScoreEngine-consistent data, each factor carrying its PIT date), and a composite-desc `/rankings`
  leaderboard **capped by the `universe_scores_top` entitlement** (Free → top-50) via `cached_rankings`.
  Reads in `analytics`, DTOs in `schemas`, envelope + disclaimer throughout. No migration. 306 tests green,
  coverage 95 % (schemas 100 %); ruff/mypy-strict/import-linter clean. QV-035 (frontend) consumes these.

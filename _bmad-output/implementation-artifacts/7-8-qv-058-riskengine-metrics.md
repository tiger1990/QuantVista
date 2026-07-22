---
baseline_commit: 9cef731273559799b1fbda7bc078155295dc141b
---

# Story 7.8: QV-058 — RiskEngine metrics

Status: review

**Epic:** EPIC-PORT (Epic 7) · **Points:** 8 · **Depends:** QV-025 (`technical_indicators` incl. `beta_1y` + PIT reader ✓), QV-051 (`portfolios`/`portfolio_positions` + `risk_snapshots` table ✓)

## Story

As a user, I want portfolio risk metrics, so that I understand my exposure — a `RiskEngine` that computes **beta, annualized volatility, max drawdown, Sharpe, Sortino, sector exposure, and concentration (HHI)** for a portfolio as of a date, persists a `risk_snapshots` row, and serves them from `GET /portfolios/{id}/risk`.

## Acceptance Criteria

1. **`RiskEngine.metrics(...)`** — pure compute over the portfolio's PIT return series + weights, returning a `RiskMetrics` value object with: `beta`, `volatility` (annualized), `max_drawdown`, `sharpe`, `sortino`, `hhi`, `sector_exposure` (dict sector→weight). All money/ratios are **Decimal**, never float, at the boundary (compute in float64, quantize out). [Source: `05` §domain `class RiskEngine.metrics(portfolio, as_of) -> RiskMetrics`]

2. **Weights = market-value with target fallback** (settled decision — [[portfolio-weight-basis]]) — per position `mv_i = shares_i × latest_close_i`; `weight_i = mv_i / Σ mv`. **Only** when the whole portfolio has no market value (`Σ mv == 0`, no shares anywhere) fall back to `target_weight` normalized. A partially-filled portfolio stays on the market-value path (no-share names correctly contribute 0). Weight derivation is one helper; the metric math is identical for both paths. After derivation (and after any thin-history renormalization) assert `|Σw − 1| ≤ WEIGHT_SUM_EPSILON` (reuse the constant from `portfolio/services.py`, same as the optimizer).

3. **Metric definitions** (annualized where noted; 252 trading days):
   - **Portfolio return series** `r_p(t) = Σ wᵢ·rᵢ(t)` from the PIT returns matrix (reuse `returns_matrix_as_of`); the weight vector is aligned to `stock_ids`.
   - **volatility** = `std(r_p, ddof=1) × √252`.
   - **beta** = `Σ wᵢ·βᵢ` using per-stock `beta_1y` from the bulk `latest_betas` reader (PIT). Names with no beta are **excluded and the weights renormalized over covered names**; record **structured** coverage `{covered, total, ratio}`.
   - **max_drawdown** = worst peak-to-trough decline of the equity curve `cumprod(1+r_p)` (**starting NAV = 1** by construction), reported as a **positive magnitude** (0.23 = a 23% drawdown).
   - **sharpe** = `(mean(r_p)×252 − rf) / (std(r_p)×√252)`, `rf` = risk-free rate from `Settings.risk_free_rate` (default 0). Guard the denominator with `_VOL_EPSILON` (see edge cases) — never divide by ~0.
   - **sortino** = `(mean(r_p)×252 − rf) / (downside_dev×√252)`, `downside_dev = sqrt(mean(min(r_p,0)²))`; same epsilon guard (no negative returns → `downside_dev ≈ 0` → `None`).
   - **hhi** = `Σ wᵢ²` (Herfindahl concentration; `1/N` diversified → `1` single-name).
   - **sector_exposure** = `{sector: Σ_{i∈sector} wᵢ}` via `sectors_for`.
   [Source: `05` §7.6 metrics list; standard definitions]

4. **Degrade gracefully, never fabricate** — with `< _MIN_OBSERVATIONS` return rows (thin/no price history), the return-series metrics (`volatility`/`max_drawdown`/`sharpe`/`sortino`) are `None` (columns are nullable) while `beta`/`hhi`/`sector_exposure` still compute from weights; the snapshot still persists with a coverage note. An **empty portfolio** (no positions) → `validation_error` (422), mirroring optimize. No silent zeros.

5. **Persist `risk_snapshots`** — upsert one row per `(portfolio_id, as_of_date)` (the table's UNIQUE); `as_of_date = latest_price_date`. `sector_exposure` → `jsonb`. Idempotent: re-hitting the endpoint the same day overwrites, doesn't duplicate. The table is **already created** in migration `0008_portfolio_risk.py` — **NO new migration** ([[forward-declared-schema-migrations]]).

6. **`GET /portfolios/{id}/risk`** — tenant-scoped (RLS-invisible/foreign/absent portfolio → 404, same `get_portfolio` guard as optimize); computes + persists + returns the metrics as Decimal **strings** in an `Envelope`, with the research-not-advice disclaimer (US-03/D1). Available to any authenticated portfolio owner — **no paid entitlement gate** (no `risk` key in the seed; risk is basic portfolio info). [Source: `backend/src/quantvista/api/routes_portfolios.py` optimize handler = the shape to mirror]

7. **Gates green** — ruff + `ruff format` + mypy (strict, whole tree via bare `mypy`) + `lint-imports` (3/3) clean; new-code coverage ≥ 80%; full backend suite green. Pure-numpy compute (no cvxpy) — `numpy` is a base dep, so this is **not** behind the `portfolio` extra.

## Tasks / Subtasks

- [x] **Task 1 — Market-data readers (bulk, PIT)** (AC: #2, #3)
  - [x] `market_data/repositories.py`: add `latest_closes(session, stock_ids, as_of) -> dict[UUID, Decimal]` — latest `daily_prices.close` with `date <= as_of` per stock (`DISTINCT ON (stock_id) ... ORDER BY stock_id, date DESC`, `stock_id = ANY(:ids)`).
  - [x] `market_data/repositories.py`: add `latest_betas(session, stock_ids, as_of) -> dict[UUID, Decimal | None]` — one query for `beta_1y` per stock, same `DISTINCT ON` PIT shape. **Avoids the N+1** of calling `technical_indicators_as_of` per holding (a code-review-rule N+1). Both readers are single-query and unit-tested for PIT (ignore future-dated rows).
- [x] **Task 2 — RiskEngine** (AC: #1, #2, #3, #4)
  - [x] `portfolio/risk.py`: `RiskMetrics` frozen dataclass (Decimal|None metric fields, `sector_exposure: dict[str, Decimal]`, `beta_coverage: Coverage` where `Coverage = (covered:int, total:int, ratio:Decimal)`) + `RiskEngine.metrics(positions, returns, betas, sectors, closes, *, risk_free_rate=Decimal(0)) -> RiskMetrics`. A `_weights(positions, closes)` helper implements AC #2 (market-value → target fallback) and asserts `|Σw−1| ≤ WEIGHT_SUM_EPSILON`. Compute in float64, quantize to Decimal at the boundary. `portfolio` may import `market_data` (DAG allows it — see `optimization/base.py`); does **not** import `analytics`.
  - [x] Constants: reuse the `_TRADING_DAYS = 252` convention; `_MIN_OBSERVATIONS` consistent with the route's returns pull; `_VOL_EPSILON = 1e-12` guarding Sharpe/Sortino denominators (near-zero std → `None`, never `inf`/NaN).
- [x] **Task 3 — Persistence** (AC: #5)
  - [x] `portfolio/repositories.py`: `upsert_risk_snapshot(session, portfolio_id, as_of_date, metrics) -> dict` — `INSERT ... ON CONFLICT (portfolio_id, as_of_date) DO UPDATE`; `tenant_id` from the RLS session GUC (match how positions/portfolios set tenant_id); `sector_exposure` as JSON. (Optional `latest_risk_snapshot` reader if a pure-read path is wanted later — not required by ACs.)
- [x] **Task 4 — Schema DTO + endpoint** (AC: #6)
  - [x] `schemas/risk.py`: `RiskResponse` (foundation-pure Pydantic; metric fields `str | None`, `sector_exposure: dict[str, str]`, `as_of_date: str`, `beta_coverage: BetaCoverageDTO {covered:int, total:int, ratio:str}`). schemas must not import a domain context.
  - [x] `config`: add `Settings.risk_free_rate: Decimal = Decimal(0)` — source `rf` from config, not a hardcoded literal (Sharpe/Sortino are correct-by-config; treasury-curve provider is future, see Deferred).
  - [x] `api/routes_portfolios.py`: `GET /portfolios/{portfolio_id}/risk` → `get_portfolio` 404 guard; `list_positions` (empty → `OptimizeError`/`validation_error` 422); `latest_price_date` (None → 422); build returns matrix (`_LOOKBACK_DAYS`/`_MIN_OBSERVATIONS`), `latest_closes`, `latest_betas`, `sectors_for`; `RiskEngine().metrics(..., risk_free_rate=settings.risk_free_rate)`; `upsert_risk_snapshot`; map → `RiskResponse`; `_with_disclaimer` + `Envelope.ok(..., meta={"disclaimer": DISCLAIMER})`.
- [x] **Task 5 — Tests** (AC: all)
  - [x] `tests/test_risk_engine.py` (unit): known-input metrics on a synthetic returns matrix + weights — vol/sharpe/sortino/drawdown vs hand-computed values; `hhi = Σw²`; `beta = Σwᵢβᵢ`; sector_exposure sums; **market-value vs target-fallback** weight selection; beta coverage renormalization + structured `beta_coverage` when a name lacks `beta_1y`; thin-history → return-series metrics `None` but beta/hhi present. **Invariants:** `1/N ≤ hhi ≤ 1`; `|Σw − 1| ≤ WEIGHT_SUM_EPSILON`. **Numerical guards:** near-zero std (e.g. constant series) → `sharpe`/`sortino` `None`, never `inf`/NaN; no negative returns → `sortino` `None`.
  - [x] `tests/integration/test_api_risk.py`: seed a Pro (or any) tenant portfolio with priced holdings → `GET /portfolios/{id}/risk` 200, Decimal-string fields, disclaimer header + meta, a `risk_snapshots` row persisted (and idempotent on a second call); empty portfolio → 422; unknown/foreign portfolio → 404. (Mirror the `test_api_optimize.py` fixture.)
  - [x] `market_data`: unit tests for `latest_closes` and `latest_betas` (PIT — ignore future-dated rows; return only the latest ≤ as_of per stock).
- [x] **Task 6 — Gates + reconcile** (AC: #7)
  - [x] Whole-tree ruff + `ruff format` + bare `mypy` + `lint-imports` (3/3) + full BE suite green; coverage ≥ 80%. Reconcile QV-058 → done after merge; **watch CI to green** ([[feedback-full-tree-gates-and-watch-ci]]).

## Dev Notes

### Reuse, don't reinvent (this is a compute+read story on existing rails)
- **Returns matrix:** `market_data/returns.py::returns_matrix_as_of(session, stock_ids, as_of, lookback_days, min_observations)` — the exact PIT reader QV-054/057 use. The `ReturnsMatrix` gives `values` (T×N float64), `stock_ids` (column order), `dates`, `dropped`. Build the weight vector aligned to `returns.stock_ids` (some positions may be dropped for thin history — renormalize the weights over surviving columns, and note it).
- **Per-stock beta:** the column is **`beta_1y`** (as `BetaFactor.column`), read via the **new bulk `latest_betas`** reader (Task 1) in one PIT query — model it on the existing `technical_indicators_as_of` window but `stock_id = ANY(:ids)` + `DISTINCT ON (stock_id)`. Do **not** loop `technical_indicators_as_of` per holding (N+1).
- **Sectors:** `market_data/repositories.py::sectors_for(session, stock_ids) -> dict[UUID, str]`.
- **`latest_price_date`, `get_portfolio`, `list_positions`, `_with_disclaimer`, `DISCLAIMER`, `Envelope`, `OptimizeError`** — all already imported in `routes_portfolios.py`; the optimize handler (`@router.post(".../optimize")`) is the shape to mirror for gating/404/disclaimer.
[Source: `backend/src/quantvista/market_data/{returns,repositories}.py`; `backend/src/quantvista/api/routes_portfolios.py`]

### Weight basis — the one design decision, already settled
Market-value (`shares × latest_close`) normalized, falling back to `target_weight` **only** when the whole portfolio has no market value. Rationale + rule in [[portfolio-weight-basis]]. This is the RiskEngine's `_weights` helper; keep the two branches in weight-derivation only so the metric math has a single path. `positions` come from `list_positions` (`stock_id`, `target_weight`, `shares`, `avg_cost`, `symbol`); `latest_close` from the new `latest_closes` reader.

### risk_snapshots is forward-declared — do NOT write a migration
`0008_portfolio_risk.py` already `CREATE TABLE risk_snapshots (... beta, volatility, max_drawdown, sharpe, sortino numeric(18,6); hhi numeric(9,6); sector_exposure jsonb; UNIQUE(portfolio_id, as_of_date))`. Writing a duplicate migration fails CI on a fresh DB (`DuplicateTable`) — [[forward-declared-schema-migrations]]. Quantize to the column scales: `numeric(18,6)` for the ratios, `numeric(9,6)` for `hhi`. Set `tenant_id` the same way the other portfolio writes do (RLS session GUC / `current_setting`).

### Decimal↔float boundary + edge cases
Compute the series metrics in float64, then `Decimal(str(x)).quantize(...)`. Guard divide-by-zero with an epsilon, not an exact-zero check: `std < _VOL_EPSILON (1e-12)` → `sharpe`/`sortino` `None` (a constant/degenerate series has std ~1e-15, which would otherwise blow up to ~1e12 — not exactly 0). **No negative returns** → `downside_dev < _VOL_EPSILON` → `sortino` `None`. `< 2` (or `< _MIN_OBSERVATIONS`) observations → all series metrics `None`. Never persist NaN/inf. Money/ratios on the wire are Decimal strings.

### As-of holdings assumption (document to prevent future look-ahead)
`list_positions` returns the portfolio's **current** holdings — there is no position-history table, so the metrics describe *today's* book priced/returned as of `latest_price_date`. This is correct while `as_of = latest_price_date`. **If a future story adds an arbitrary `as_of`**, holdings must also be reconstructed as-of that date (a position-history/lot table) or the beta/prices become PIT-clean while the *weights* silently leak current holdings into the past. Callers must not pass a historical `as_of` against current positions.

### Complexity
`O(T×N)` time and memory for the return series (T return days × N holdings) — the dominant cost is the returns-matrix build; the metric reductions are `O(T·N)`/`O(N)`. Fine for retail Nifty-200 portfolios (N ≤ ~few dozen). No pagination/streaming needed.

### Deferred / future extensibility (reviewed, intentionally NOT in this story)
Captured so they aren't lost — none are blockers for the "understand my exposure" AC:
- **Historical (regression) beta** `Cov(R_p, R_m)/Var(R_m)` and a **benchmark series** (`benchmark_id`: NIFTY 50/200 TRI) — needs a benchmark return series we don't plumb yet; the per-stock `beta_1y` weighted sum is the standard portfolio beta until then. Expose both (`weighted_beta`, `historical_beta`) once a benchmark lands (pairs naturally with QV-062/backtest benchmark work).
- **Treasury-curve risk-free provider** — `Settings.risk_free_rate` (this story) is the seam; a real curve is later.
- **Cached snapshot reads + `force_refresh`** — compute is ms and there's no load; recompute-always is correct now. Add read-cache when the endpoint is hot.
- **Single-flight / advisory lock** — the `ON CONFLICT` upsert is already race-safe for persistence; concurrent compute is wasteful but not incorrect.
- **Observability counters** (`risk_compute_latency`, `risk_missing_beta`, …) — wire when this becomes a hot path; fits the existing `ops/` Prometheus setup.

### Bounded-context / DAG
`RiskEngine` lives in the **portfolio** context and may import **market_data** (`portfolio → … → market_data`, already done by `optimization/base.py`). It must **not** import `analytics` (that would violate the layer order — read `beta_1y` from the `market_data` repo directly, not via `analytics.ScoringContext`). `schemas/risk.py` stays foundation-pure (no domain import); the domain→DTO mapping lives in the api layer. `lint-imports` (3 contracts) must stay green. [Source: [[backend-layout-quantvista-namespace]]; `pyproject.toml` importlinter]

### Entitlement
No `risk` key exists in `seed_reference.sql`, and the story is "As a **user**" — serve risk to any authenticated portfolio owner (tenant-scoped RLS 404 is the only gate). If the PRD tier matrix later wants to gate it, it's a one-line `entitlements.check(...)` like optimize — out of scope here.

### Scope boundary (NOT this story)
- Rebalancing / drift alerts → QV-059 (will consume market-value vs target).
- Risk dashboard UI + drawdown chart → QV-060 (this story is BE + endpoint only).
- Multi-tenant isolation proof tests → QV-061.
- Scheduled/backfilled snapshots — this endpoint computes on demand; no cron.

### References
- [Source: `plans/sprints/sprint-07-portfolio-ii-risk.md#QV-058`] — AC (beta, vol, drawdown, Sharpe, Sortino, sector exposure, HHI; persist `risk_snapshots`; `GET /portfolios/{id}/risk`)
- [Source: `plans/05-domain-and-quant.md` §domain `RiskEngine`, §7.6] — engine seam + metric list
- [Source: `backend/src/quantvista/db/migrations/versions/0008_portfolio_risk.py`] — the `risk_snapshots` columns/scales (already created)
- [Source: `backend/src/quantvista/analytics/factors.py`] — `BetaFactor.column = "beta_1y"` (the indicator to read)
- [Source: `backend/src/quantvista/portfolio/optimization/base.py`] — the reuse pattern (portfolio importing market_data; Decimal↔float boundary)
- [Source: `[[portfolio-weight-basis]]`, `[[forward-declared-schema-migrations]]`, `[[backend-layout-quantvista-namespace]]`]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (dev-story)

### Debug Log References

- The synthetic returns matrix for the reference test initially produced a **non-negative** portfolio series (Sortino correctly `None`, but the reference expected a value) — adjusted the fixture so the portfolio series has a genuine negative day. Confirms the epsilon guard fires exactly when downside deviation is ~0.
- `mypy src tests` (my invocation) vs CI: CI runs **bare `mypy`** whose `files` includes `scripts`; bare mypy is green (239 files). Same gotcha as QV-057.
- `close` vs `adj_close`: the returns matrix uses `adj_close` (corporate-action adjusted) for returns; market-value **weights** use raw `close` (actual traded price) — `latest_closes` reads `close`.

### Completion Notes List

- **Bulk PIT readers (Task 1):** `latest_closes` + `latest_betas` — one `DISTINCT ON (stock_id)` query each (no N+1, per the review). PIT-verified (future-dated bar/indicator invisible; NULL beta → `None`; missing → omitted).
- **RiskEngine (Task 2):** pure compute (`portfolio/risk.py`) — market-value weights with target→equal-weight fallback + `|Σw−1| ≤ WEIGHT_SUM_EPSILON` assertion; beta = Σwᵢβᵢ renormalized over covered names with structured `BetaCoverage`; vol/Sharpe/Sortino/max-drawdown off the portfolio return series with `_VOL_EPSILON` guards (near-zero std/downside → `None`, never inf/NaN); HHI = Σwᵢ²; sector exposure via `sectors_for`. Decimal↔float boundary (quantize to 6dp). Imports `market_data` only (not `analytics`).
- **Persistence (Task 3):** `upsert_risk_snapshot` — `ON CONFLICT (portfolio_id, as_of_date) DO UPDATE`, `tenant_id` explicit (RLS INSERT), `sector_exposure` as `jsonb` Decimal-strings. No migration (forward-declared in `0008`).
- **Endpoint (Task 4):** `GET /portfolios/{id}/risk` — `get_portfolio` 404 guard, empty/no-price → 422, computes + persists + returns Decimal strings + disclaimer. No paid gate. `Settings.risk_free_rate` (default 0) sources `rf`.
- **Review items folded in:** bulk beta reader, epsilon guards, Σw assertion, HHI invariant test, config rf, structured coverage, as-of-holdings + O(T×N) docs. Deferred items (historical/benchmark beta, treasury rf, cached reads, single-flight, observability) recorded with rationale.
- **Gates:** ruff + `ruff format` + bare mypy (239) + lint-imports (3/3) clean; **610 passed / 5 skipped** (no regressions, +17 tests); **99%** coverage on `portfolio/risk.py`, 100% on `schemas/risk.py`.

### File List

**Backend — new**
- `backend/src/quantvista/portfolio/risk.py` — `RiskEngine`, `RiskMetrics`, `BetaCoverage`
- `backend/src/quantvista/schemas/risk.py` — `RiskResponse`, `BetaCoverageDTO`
- `backend/tests/test_risk_engine.py` — RiskEngine unit tests (10)
- `backend/tests/integration/test_api_risk.py` — endpoint e2e (4)
- `backend/tests/integration/test_bulk_pit_readers.py` — `latest_closes`/`latest_betas` PIT (3)

**Backend — modified**
- `backend/src/quantvista/market_data/repositories.py` — `latest_closes`, `latest_betas` (bulk PIT readers)
- `backend/src/quantvista/portfolio/repositories.py` — `upsert_risk_snapshot`
- `backend/src/quantvista/api/routes_portfolios.py` — `GET /portfolios/{id}/risk` endpoint + imports
- `backend/src/quantvista/core/config.py` — `Settings.risk_free_rate`

## Change Log

- QV-058 story drafted (ready-for-dev): `RiskEngine` computing beta (Σwᵢ·beta_1y, coverage-renormalized) / annualized vol / max drawdown / Sharpe / Sortino / HHI / sector exposure over the PIT returns matrix, on **market-value weights with target fallback** ([[portfolio-weight-basis]]); persists the forward-declared `risk_snapshots` (no migration); `GET /portfolios/{id}/risk` (tenant-scoped, no paid gate, disclaimer). Reuse-heavy (returns matrix, `sectors_for`); two new bulk PIT readers (`latest_closes`, `latest_betas` — no N+1); pure numpy (no cvxpy extra).
- Incorporated external review (2026-07-22, score 9.1): folded in bulk beta reader (N+1 fix), epsilon numerical guards for Sharpe/Sortino, `Σw≈1` assertion, HHI invariant tests, config-driven risk-free rate, structured `beta_coverage`, and documented the as-of-holdings assumption + O(T×N) complexity. Deferred (with rationale): historical/benchmark beta, treasury-curve rf, cached reads/force_refresh, single-flight concurrency, observability counters — none block the AC.

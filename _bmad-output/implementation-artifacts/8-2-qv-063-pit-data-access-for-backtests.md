---
baseline_commit: 541b4e11cf6ee191c845d14b2958e80ce84437a3
---

# Story 8.2: QV-063 — PIT data access for backtests

Status: review

**Epic:** EPIC-BT (Epic 8) · **Points:** 8 · **Depends:** QV-021 (bitemporal fundamentals), QV-030 (compute factors/scores), QV-028/029 (Factor/ScoreEngine + `ScoringContext`)

> **The look-ahead firewall for backtests.** This story builds the **point-in-time (PIT) read layer** the backtest engine (QV-065) will consume: given a rebalance date `D`, it exposes the scored/ranked universe and adjusted returns computed from **only data knowable by end of `D`** — and is *structurally* unable to see post-`D` data. It composes the existing as-of readers (does NOT re-implement scoring). It does **not** run the rebalance loop (QV-065) and does **not** resolve survivorship-free membership (QV-064) — the universe is caller-supplied.

## Story

As a quant, I want the engine to read only data knowable at each rebalance date, so there's no look-ahead bias.

## Acceptance Criteria

1. **A single PIT read seam** — `BacktestDataAccess(session)` (new, `analytics/backtest_data.py`) is the **only** way QV-065 reads market/score data. Every method takes an `as_of: date` and returns data bounded by knowledge ≤ `as_of`. It **structurally cannot** expose post-`as_of` data — there is no method that reads "latest"/unbounded, and `as_of` is threaded into every underlying query.
   [Source: `05` §4.1; `03` §5; project rule #4]

2. **Ranked universe at `D`** — `ranked_universe(as_of, universe, *, rank_by, top_n) -> list[UUID]` returns the top-`top_n` stock ids by the `rank_by` score, computed **PIT at `as_of`** by reusing `analytics.scoring.compute_universe(session, as_of, universe)` (which runs the Factor/Score engines through `ScoringContext` — the QV-037 no-look-ahead defense: fundamentals via bitemporal knowledge-time = end of `as_of` day, indicators/sentiment `date ≤ as_of`). Names with no score for the metric are excluded; ties broken deterministically (by score desc, then stock_id) for reproducibility. `rank_by ∈ {composite, fundamental, momentum, quality, sentiment, risk}` (the `BacktestSpec` set).
   [Source: `analytics/scoring.compute_universe`; `analytics/context.ScoringContext`; QV-028/029]

3. **Adjusted returns at `D`** — `returns_as_of(as_of, stock_ids, *, lookback_days) -> ReturnsMatrix` reuses `market_data.returns.returns_matrix_as_of` (already `date ≤ as_of`, adjusted close, thin names dropped). This is the return series the engine uses between rebalances. No raw/unbounded price reads leak in.
   [Source: `market_data/returns.returns_matrix_as_of` (QV-054)]

4. **Structural no-look-ahead — proven by a leakage regression** — a real-Postgres counterfactual test (mirror QV-037 `test_scoring_leakage.py`): build a universe with data pre-`as_of`, capture `ranked_universe(EARLY, …)` = baseline; inject **post-`EARLY` trap data** (future-dated indicators + a later-knowledge fundamentals restatement + post-`EARLY` prices — extreme enough to reorder the ranking); recompute `ranked_universe(EARLY, …)` → **identical** (no leak). A companion **"trap has teeth"** assertion proves `ranked_universe(LATE, …)` (where the trap IS knowable) **differs** — so the test is non-vacuous. Also assert `returns_as_of(EARLY, …)` sees no post-`EARLY` bar.
   [Source: `05` §1.1; QV-037 pattern; `06`/QV-066 bias suite continues this]

5. **Deterministic + reproducible** — for a fixed `(as_of, universe, rank_by, top_n)` and unchanged data, `ranked_universe` returns the identical ordered list every call (seed-free — it's a pure function of PIT data). `MODEL_VERSION` (score-v1) is the methodology fingerprint carried through `compute_universe`.
   [Source: `03` §9 reproducibility; `analytics.scoring.MODEL_VERSION`]

6. **Tests + gates** — unit (rank_by/top_n selection, exclusion of unscored names, deterministic tie-break) + integration leakage regression (`@pytest.mark.integration`, runs in `backend-rls`, **non-skippable** in that job). Coverage ≥80% on the new module. Full-tree gates green. **No API/schema/migration** (internal read layer for QV-065).
   [Source: testing rules; QV-037 precedent]

---

## Dev Notes

### Placement & DAG

- New file **`analytics/backtest_data.py`** — `BacktestDataAccess`, next to `analytics/backtest.py` (the QV-062 engine seam). DAG: `analytics → market_data` (returns) is already allowed; `analytics` may use its own `scoring`/`context`. No new context, no DAG change (confirm `lint-imports` 3/3).
- **Pure-ish read layer:** takes a `Session`, composes existing readers. No API, no schema, no migration, no new dependency. This is the seam QV-065 depends on.
- Python 3.13, mypy strict, ruff 0.16.x. Money/returns stay Decimal→float only inside numpy (as the risk/optimizer layers do); ids are `UUID`.

### Reuse — do NOT re-implement (critical)

- **PIT scores:** `analytics/scoring.py::compute_universe(session, as_of, universe) -> Sequence[StockScore]`. It builds `FactorEngine.compute_factor_values` + `ScoreEngine.compute_scores` over a `ScoringContext(session, as_of, universe)` — **the existing look-ahead firewall** (`analytics/context.py`: `fundamentals_as_of` at end-of-`as_of`-day knowledge-time, `indicator_as_of` `date ≤ as_of`, `sentiment_as_of` bounded). `ranked_universe` calls this, reads the `rank_by` sub-score off each `StockScore`, filters `None`, sorts desc + tie-breaks by stock_id, slices `top_n`. **Never** query the `scores` table directly for a backtest (that would read whatever a job persisted, not a clean as-of recompute).
- **PIT returns:** `market_data/returns.py::returns_matrix_as_of(session, stock_ids, as_of, *, lookback_days, min_observations)` — already `date ≤ as_of`, adjusted close, `ReturnsMatrix(values, stock_ids, dates, dropped)`. Wrap it; do not re-query prices.
- **StockScore fields** (from `analytics/scoring.py` / QV-029/046): `composite`, `fundamental_score`/etc. — map `rank_by` → the field. Check the exact attribute names on `StockScore` before wiring (`grep "class StockScore"`); the `rank_by` enum values were chosen in QV-062 to match.

### The `ScoringContext` guarantee (why this is the firewall)

`analytics/context.py` header: *"Cannot read 'latest' data: every read is bounded by `as_of`. The structural defence against look-ahead bias (05 §1.1)."* `compute_universe(session, as_of, universe)` only ever reads through it. So `ranked_universe` inherits the guarantee **for free** — the leakage test proves it end-to-end for the backtest seam. Do not add any bypass (e.g. a "current score" fast path).

### Leakage test — build on QV-037

`tests/integration/test_scoring_leakage.py` is the template: `EARLY`/`LATE` dates, a 3-stock universe seeded pre-`EARLY` with cross-sectionally varied `(ret_6m, beta_1y, pe)`, `_inject_trap(admin_engine, stock_ids)` writing **future-dated indicators + later-knowledge pe restatement**, and both the "unchanged" + "trap has teeth" assertions. QV-063's test asserts the same at the **`ranked_universe`** level (the ordered id list is identical at `EARLY` before/after the trap; differs at `LATE`), plus a `returns_as_of` no-future-bar check. Reuse its seeding helpers/shape. Keep it **non-skippable** in `backend-rls` (real PG; the collection guard only skips when no DB is reachable).

### Universe & membership (scope boundary)

`ranked_universe` takes `universe: Sequence[UUID]` from the caller. **Survivorship-free historical membership is QV-064** — until then, tests pass a fixed list, and QV-065 will resolve membership per rebalance date via QV-064. Do NOT resolve `index_constituents` here. (Document this clearly so QV-065 wires QV-064 → the `universe` arg.)

### Previous-story / epic intelligence

- **QV-062 (just merged):** `BacktestSpec` (`schemas/backtest.py`) defines `rank_by`/`top_n`/`rebalance`/dates — `ranked_universe`'s `rank_by`/`top_n` come straight from it. The `BacktestEngine.run` placeholder (`analytics/backtest.py`) is where QV-065 will call `BacktestDataAccess`. `core.tasks.enqueue` + the async plumbing already exist.
- **QV-037:** the leakage-regression pattern + `test_scoring_leakage.py` fixtures to mirror.
- **QV-061 lesson:** integration tests share the DB — scope assertions to the test's own seeded stock ids; don't assert global counts.
- **De-flake lesson (this session):** never assert on shared/global state; the dev DB persists across runs. [[feedback-investigate-flaky-tests]]
- **Scoring methodology:** `MODEL_VERSION="score-v1"`; robust-z/learned-weights are v2 (roadmap) — not this story. [[scoring-methodology-roadmap]]

### Git intelligence (recent)

`541b4e1` QV-062 backtest async · `e7c1ead` QV-061 isolation · `66667dd` QV-079. The scoring stack (QV-028/029/030), `ScoringContext`, `returns_matrix_as_of`, and the QV-037 leakage test are all in `master` — this story is composition + a proof test, no new machinery.

### Project context reference

`_bmad-output/project-context.md` rule #4 (**PIT correctness is non-negotiable — no look-ahead/survivorship; bias-regression tests run in CI**) is the whole point of this story. Also: quant factors return `None` → excluded (don't impute), reproducible scoring via `model_version`. Related: [[scoring-methodology-roadmap]], [[dev-fundamentals-empty-by-design]] / [[fundamentals-from-yfinance-statements]] (dev fundamentals coverage), [[backend-layout-quantvista-namespace]].

---

## Tasks / Subtasks

### Task 1: BacktestDataAccess — PIT read seam
- [x] 1a. Confirm the exact `StockScore` attribute names for each `rank_by` value (`grep "class StockScore"` in `analytics/scoring.py`); map `rank_by` → attribute
- [x] 1b. Create `analytics/backtest_data.py` — `BacktestDataAccess(session)` with `ranked_universe(as_of, universe, *, rank_by, top_n)` (reuse `compute_universe`, read `rank_by` sub-score, drop `None`, sort desc + tie-break by stock_id, slice `top_n`) and `returns_as_of(as_of, stock_ids, *, lookback_days, min_observations)` (wrap `returns_matrix_as_of`)
- [x] 1c. No method exposes unbounded/"latest" data; `as_of` threaded everywhere

### Task 2: Unit tests (pure selection logic)
- [x] 2a. `tests/integration/test_backtest_data.py` (needs PG for `compute_universe`) OR a unit test with a small seeded universe: `ranked_universe` returns top-N by the metric, excludes unscored names, deterministic order (stable tie-break)
- [x] 2b. `rank_by` variants map to the right sub-score; `top_n` caps the list

### Task 3: Leakage regression (the AC-4 firewall proof)
- [x] 3a. Mirror `test_scoring_leakage.py`: seed a small universe pre-`EARLY`; `ranked_universe(EARLY)` = baseline
- [x] 3b. Inject post-`EARLY` trap (future indicators + later-knowledge fundamentals restatement + post-`EARLY` prices); assert `ranked_universe(EARLY)` **unchanged** (no leak)
- [x] 3c. "Trap has teeth": `ranked_universe(LATE)` **differs** (trap now knowable) — non-vacuous
- [x] 3d. `returns_as_of(EARLY, …)` includes no post-`EARLY` bar (assert max date ≤ EARLY)
- [x] 3e. `@pytest.mark.integration`, non-skippable in `backend-rls`

### Task 4: Gates + sprint status
- [x] 4a. Full-tree gates: `ruff check . && ruff format --check . && mypy && lint-imports && bandit -c pyproject.toml -r src/ -ll -q && pip-audit --skip-editable && pytest` — green (no regressions)
- [x] 4b. Coverage ≥80% on `analytics/backtest_data.py`
- [x] 4c. Update `sprint-status.yaml` → review; fill Dev Agent Record

---

## Dev Agent Record

### Debug Log

- `compute_universe`'s real signature is `(session, universe, as_of)` — universe **before** as_of (the story draft had them swapped); wired correctly.
- `StockScore` exposes exactly the `rank_by` set as attributes (`composite`/`fundamental`/`momentum`/`quality`/`sentiment`/`risk`) → `getattr(score, rank_by)` maps directly; `composite` is always present, the sub-scores are `float | None` (excluded when None).
- Test-helper bug: `_ranked` hard-coded `top_n=3` while a caller also passed `top_n` via `**kw` → duplicate-kwarg TypeError; gave the helper explicit `rank_by`/`top_n` params.

### Completion Notes List

- **`analytics/backtest_data.py` — `BacktestDataAccess(session)`**: the single PIT read seam for the backtest engine (QV-065). `ranked_universe(as_of, universe, *, rank_by, top_n)` **reuses `compute_universe`** (Factor/Score engines through `ScoringContext` — the QV-037 firewall), reads the `rank_by` sub-score, excludes `None`, sorts score-desc + stock_id-asc (deterministic), slices `top_n`; unknown `rank_by` → `ValueError`. `returns_as_of(...)` **wraps `returns_matrix_as_of`** (already `date ≤ as_of`). No "latest"/unbounded read exists → structurally no look-ahead.
- **Leakage regression** (`tests/integration/test_backtest_data.py`, mirrors QV-037): ranking at `EARLY` is byte-identical before/after injecting post-`EARLY` trap (future indicators + later-knowledge fundamentals restatement + a post-`EARLY` price bar); **"trap has teeth"** — `LATE` ranking differs (non-vacuous); `returns_as_of(EARLY)` has `max(dates) ≤ EARLY`. Plus selection tests (top_n cap, determinism, bad-metric `ValueError`).
- **Scope boundaries honoured:** `universe` is caller-supplied (survivorship-free membership = QV-064); no rebalance loop (QV-065); no `index_constituents` resolution here.
- **Gates:** full suite **701 passed / 5 skipped**; ruff/format/mypy(264)/lint-imports(3/3)/bandit/pip-audit green; **100%** coverage on the new module. **No API/schema/migration, no new dependency.** DAG unchanged (`analytics → market_data` already allowed).

### File List

**New**
- `backend/src/quantvista/analytics/backtest_data.py` — `BacktestDataAccess` PIT read seam
- `backend/tests/integration/test_backtest_data.py` — selection + leakage-regression tests

### Change Log

- **2026-07-27 — QV-063 PIT data access for backtests.** Added `BacktestDataAccess` — the look-ahead firewall the QV-065 engine reads through: `ranked_universe` (PIT scores via `compute_universe`/`ScoringContext`, deterministic top-N) + `returns_as_of` (via `returns_matrix_as_of`), with no unbounded read path. Proven by a QV-037-style leakage regression (post-as_of trap invisible at EARLY; teeth at LATE; no future return bar). Universe caller-supplied (membership = QV-064). 701 passed/5 skipped; 100% new-module coverage; no migration/dependency.

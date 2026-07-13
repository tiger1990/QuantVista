---
baseline_commit: 560f6104f18735a7311d21b3de6ba1fb292b6fb6
---

# Story 7.4: QV-054 — Mean-Variance optimizer (shrinkage covariance)

Status: review

**Epic:** EPIC-PORT (Epic 7) · **Points:** 8 · **Depends:** QV-053 (`Constraints`/`check`/`feasibility`/`InfeasibleConstraints` ✓ done), QV-025 (technical indicators / `daily_prices.adj_close` history ✓)

## Story

As a quant, I want Markowitz mean-variance optimization with a **stable (Ledoit-Wolf shrinkage) covariance** and a real convex solver, so that allocations are sensible and robust — weights sum to 1.0, every QV-053 constraint is respected, and an infeasible problem reports its **binding constraint** (US-03) instead of silently returning garbage.

## Acceptance Criteria

1. **`MeanVarianceOptimizer`** — implements the `IOptimizer` seam and supports three objectives: `min_vol` (minimize `wᵀΣw`), `target_return` (min variance s.t. `μᵀw ≥ target`), and `max_sharpe` (maximize `(μ−r_f)ᵀw / √(wᵀΣw)` via the standard convex y-reformulation). Solved with **CVXPY + OSQP**. Returns weights that **sum to 1.0** (within `WEIGHT_SUM_EPSILON`) plus the achieved **expected return** and **expected volatility** (annualized). [Source: `05` §1.3/§3; `plans/sprints/sprint-06-portfolio-i.md#QV-054`]

2. **Ledoit-Wolf shrinkage covariance** — a hand-rolled NumPy `LedoitWolfEstimator` (no scikit-learn in prod) behind a `CovarianceEstimator` Protocol, with a `SampleCovarianceEstimator` baseline. Shrinks the sample covariance toward a structured target; returns a symmetric PSD matrix. Sample covariance instability is **risk R7** (`09` §5) — shrinkage is the mitigation, not optional. [Source: `05` §3; `09` §5]

3. **Constraints respected (QV-053 reuse)** — the optimizer consumes QV-053's `Constraints` and enforces them **in the solve**: `long_only` (`w ≥ 0`), `max_weight`/`min_weight` (per-name bounds), `sector_caps` (per-sector aggregate ≤ cap), `cardinality`* and `max_turnover`* where expressible, `target_return`/`target_volatility`. The final Decimal allocation is **validated through QV-053 `check()`** before return — the optimizer must never return an allocation that fails its own constraints. (*cardinality/turnover: see Dev Notes — cardinality is non-convex; scope note.)

4. **Infeasible → binding constraint (US-03)** — before solving, run QV-053 `feasibility(...)` as a structural pre-check; if the CVXPY solve returns `infeasible`/`unbounded`/non-`optimal`, raise QV-053's **`InfeasibleConstraints`** carrying the binding constraint (derived from the structural check, or by probing which constraint blocks the solve). No silent failure, no `None`/degenerate weights. Consumers (QV-055) map this to `error.code="infeasible"` (422).

5. **PIT returns-matrix reader** — a new `market_data` reader assembles a returns matrix from `daily_prices.adj_close` for a candidate universe over a lookback window, **point-in-time bounded** (`date <= as_of`, no look-ahead — project rule #4). Aligns names on common dates, drops names with insufficient history (return the dropped ids so the caller knows). `daily_prices` is a **global table** (no `tenant_id`/RLS — rule #1); the optimizer takes the resulting matrix (`NDArray`), never a `Session` (it stays pure compute, DB-agnostic).

6. **Decimal ↔ float boundary is explicit and correct** — `Constraints`/weights are `Decimal` (money rule); NumPy/CVXPY are `float64`. The optimizer converts Decimal inputs → float for the solve, then **quantizes** the float weights back to `Decimal`, **re-normalizes** so `Σw = 1.0` within `WEIGHT_SUM_EPSILON`, and only then builds the `Allocation` for `check()`. Money/weights on the wire are `Decimal`, never `float`.

7. **Dependencies as an optional extra + gates green** — `cvxpy`/`osqp` added as a new **optional `portfolio` extra** in `pyproject.toml` (base install stays lean, mirroring `finbert`/`kafka`/`dev-data`); `cvxpy` added to the mypy untyped-modules override. ruff + `ruff format` + mypy (strict, whole tree) + `lint-imports` clean; new-code coverage ≥ 80%. **Verified locally**: `cvxpy 1.9.2` + `osqp 1.1.3` install and solve a 50-asset constrained QP on this box (macOS 12 x86_64 / Py 3.13) — optimizer tests are **not** environment-gated (unlike FinBERT). [Source: `[[cvxpy-osqp-local-feasibility]]`]

## Tasks / Subtasks

- [x] **Task 1 — Dependency plumbing** (AC: #7)
  - [x] `pyproject.toml`: add `portfolio = ["cvxpy>=1.5", "osqp>=0.6"]` under `[project.optional-dependencies]` with a justification comment (Clarabel/SCS ship bundled with cvxpy — do **not** list a second backend; YAGNI until a story needs it).
  - [x] Add `cvxpy`/`osqp` to the mypy untyped-modules override (they ship no py.typed), same shape as the `exchange_calendars`/`pandas` block.
  - [x] Confirm `pip install -e .[portfolio]` is satisfied in `backend/.venv` (already installed during planning; this just formalizes it).
- [x] **Task 2 — Covariance estimators** (AC: #2)
  - [x] `portfolio/covariance.py`: `CovarianceEstimator` Protocol (`estimate(returns: NDArray[float64]) -> NDArray[float64]`); `SampleCovarianceEstimator` (baseline); `LedoitWolfEstimator` — hand-rolled LW shrinkage toward a structured target (constant-correlation or scaled-identity; state which), returning a **symmetric PSD** matrix. NumPy only.
  - [x] Guardrails: shrinkage intensity δ clamped to `[0, 1]`; handle the degenerate single-asset / zero-variance case without dividing by zero.
- [x] **Task 3 — PIT returns-matrix reader** (AC: #5)
  - [x] `market_data/repositories.py`: `returns_matrix_as_of(session, stock_ids, as_of, *, lookback_days|min_obs) -> ReturnsMatrix` — SELECT `(stock_id, date, adj_close)` for the ids where `date <= as_of`, ordered; compute **simple** returns; align on common dates; drop names with insufficient history and report them. Return the matrix, the surviving ordered `stock_id`s, and the date span. No `tenant_id`/RLS (global table).
  - [x] A small frozen `ReturnsMatrix` value object (`values: NDArray`, `stock_ids: tuple[UUID, ...]`, `dates: tuple[date, ...]`) so shape/identity stay coupled.
- [x] **Task 4 — `MeanVarianceOptimizer` + request/result models** (AC: #1, #3, #4, #6)
  - [x] `portfolio/optimizer.py`: `Objective` enum (`MIN_VOL`, `TARGET_RETURN`, `MAX_SHARPE`); frozen `OptimizationRequest {objective, constraints: Constraints, risk_free_rate: Decimal = 0, ...}` and `OptimizationResult {weights: dict[UUID, Decimal], expected_return: Decimal, expected_volatility: Decimal, constraint_report: ConstraintReport}`.
  - [x] Expected returns μ = annualized historical mean from the returns matrix; covariance Σ = `CovarianceEstimator.estimate(...)` annualized (factor 252). State the annualization + μ-source assumptions in the docstring (score-derived μ / Black-Litterman is a **later** enhancement — out of scope).
  - [x] Build the CVXPY problem per objective (min_vol; target_return with `μᵀw ≥ target`; max_sharpe via the y=κw reformulation — constraints scale by κ, `w = y/κ`); translate `Constraints` → CVXPY constraints (sector caps via a sector-membership matrix). Solve with `cp.OSQP` (wrap Σ in `cp.psd_wrap`).
  - [x] **Decimal↔float boundary** (AC #6): float solve → quantize weights to Decimal → re-normalize to `Σw=1±ε` → build `Allocation` → QV-053 `check()`; return the report in the result.
  - [x] **Infeasible path** (AC #4): pre-check `feasibility(...)`; if solve status ≠ `optimal` (or `check()` fails post-solve), raise `InfeasibleConstraints(binding)`.
  - [x] Contain all CVXPY usage in this module (so QV-057 can later extract a solver seam cleanly — see Framework expansion note).
- [x] **Task 5 — Refine `IOptimizer` seam** (AC: #1)
  - [x] `portfolio/interfaces.py`: tighten `IOptimizer` to the typed `optimize(request: OptimizationRequest, returns: ReturnsMatrix) -> OptimizationResult` (replacing the placeholder `optimize(spec: dict) -> dict`). Keep it minimal; `MeanVarianceOptimizer` implements it. Do not add risk-parity/BL yet.
- [x] **Task 6 — Tests** (AC: all)
  - [x] `tests/test_portfolio_covariance.py`: LW returns symmetric + PSD (all eigenvalues ≥ 0); δ ∈ [0,1]; shrinks toward target as noise grows; **cross-validate against `sklearn.covariance.LedoitWolf` within atol** using `pytest.importorskip("sklearn")` (dev-only, skips if absent — sklearn never a prod/CI-hard dep); single-asset / zero-variance degenerate case.
  - [x] `tests/test_portfolio_optimizer.py`: each objective solves to `optimal` on a synthetic SPD covariance; **`Σw = 1.0`** within ε; long-only, max_weight, sector_caps, target_return all respected in the result (asserted via QV-053 `check()` feasible); `max_sharpe` result has Sharpe ≥ the `min_vol` and `target_return` solutions on the same inputs; **infeasible** case (target_return above achievable) raises `InfeasibleConstraints` with the expected binding kind; Decimal round-trip (weights are `Decimal`, sum exactly 1 within ε).
  - [x] `tests/test_returns_matrix.py` (integration, DB): PIT boundary (`date <= as_of` excludes a future-dated bar); alignment on common dates; insufficient-history names dropped + reported. Uses the admin-engine seed harness (markets/stocks/daily_prices), mirroring `test_portfolio_repository.py`.
- [x] **Task 7 — Gates + reconcile** (AC: #7)
  - [x] Whole-tree `ruff check .` + `ruff format --check .` + `mypy` (strict) + `lint-imports` (3/3) clean; full suite green; new-code coverage ≥ 80%. Reconcile QV-054 → done after merge. **Watch CI to green before reporting done** ([[feedback-full-tree-gates-and-watch-ci]]).

## Dev Notes

### Decision locked with Deepak Sir (2026-07-13): CVXPY+OSQP, NumPy Ledoit-Wolf, pluggable estimator
The optimizer stack was chosen deliberately for the whole Epic-7 optimizer family (QV-054 MV now; QV-057 risk-parity, QV-064 backtest, later BL/HRP). **CVXPY + OSQP** because mean-variance is a textbook convex QP — CVXPY guarantees the global optimum, its DSL mirrors the papers, and it scales to the real 50–200-name **candidate** universe (Nifty 200 → filter → top 50–100 → optimize → 15–25 holdings), not just the final book. **Verified on this box**: cvxpy 1.9.2 + osqp 1.1.3 install (scs builds from source cleanly) and solve a 50-asset constrained QP in ~26 ms (`optimal`, Σw=1, caps respected); an over-tight target-return returns `infeasible`. This is the **opposite** of the torch/FinBERT situation — the optimizer is locally testable, so its tests are NOT CI-Linux-gated. [Source: `[[cvxpy-osqp-local-feasibility]]`]

### Framework expansion is deferred on purpose (YAGNI now, full solver by end of Epic 7)
Deepak Sir's directive: ship the **choices** now, keep it lean, and **I decide when to expand** — with the full solver framework in place by the **end of Epic 7**. So QV-054 ships **flat modules** (`portfolio/covariance.py`, `portfolio/optimizer.py`) plus the one cheap seam that has a real second consumer (the `CovarianceEstimator` Protocol — QV-058 RiskEngine needs covariance too). It does **NOT** build, this story: a solver-swap `OptimizationSolver`/`OptimizationProblem` abstraction, an `Objective` strategy hierarchy, a `domain/covariance/optimizers/solvers/services` subpackage tree, or placeholder files for unwritten optimizers. Those are speculative generality against stories that don't exist yet (project rule: *"avoid speculative generality; refactor when the pressure is real"*). **Planned expansion timing:** QV-057 (risk parity) is the natural point to extract the solver/objective abstraction and grow the subpackage tree — a deliberate refactor against a real second optimizer. Keep all CVXPY usage contained in `optimizer.py` now so that extraction is mechanical later. **Do NOT relocate the already-merged `portfolio/constraints.py`** (QV-053, PR #60) into a `domain/` tree in this story.

### Reuse QV-053 — do not reinvent constraints
`portfolio/constraints.py` is done and merged: `Constraints` (frozen, Decimal), `Allocation`, `check()` (per-constraint `ConstraintReport`), `feasibility()` (structural pre-check), `InfeasibleConstraints` + `raise_if_infeasible`, and `WEIGHT_SUM_EPSILON`. QV-054 **consumes** these: translate `Constraints` → CVXPY constraints for the solve; `feasibility()` as the pre-check; `check()` as the post-solve guard; reuse `WEIGHT_SUM_EPSILON` for the sum-to-1 tolerance (don't define a new epsilon). [Source: `backend/src/quantvista/portfolio/constraints.py`]

### The Decimal ↔ float boundary is the real bug surface (test it hard)
QV-053 is Decimal; NumPy/CVXPY are float64. The single most likely defect is a weights vector that sums to `0.9999998` or a constraint that passes in float but fails QV-053's Decimal `check()`. Discipline: (1) Decimal → float only at the solve boundary; (2) quantize the float solution to a fixed Decimal precision (e.g. `numeric(9,6)` like the positions table); (3) re-normalize so `Σw = 1` within `WEIGHT_SUM_EPSILON` (distribute the rounding residual to the largest weight); (4) build `Allocation` and run `check()`; (5) return the Decimal weights + the report. Never leak a float weight to the wire. [Source: `[[market-data-provider-strategy]]` money rule; `backend/src/quantvista/portfolio/constraints.py`]

### max_sharpe is the subtle objective
`min_vol` and `target_return` are direct convex QPs. **max_sharpe** (a ratio) is not directly convex; use the standard **homogenization**: with `y = κw, κ ≥ 0`, minimize `yᵀΣy` s.t. `(μ − r_f)ᵀy = 1`, `Σyᵢ = κ`, and every linear constraint scaled by κ (`0 ≤ y ≤ κ·max_weight`, sector: `A y ≤ κ·caps`), then recover `w = y / κ`. Assert in tests that the max_sharpe result's Sharpe ≥ the min_vol and target_return solutions on identical inputs. If a clean reformulation for a given constraint set proves intractable within this story, HALT and confirm scope with the user rather than shipping a wrong max_sharpe. [Source: `05` §3; standard MV literature]

### Expected returns & covariance inputs (state the modeling assumptions)
For the MVP: **μ = annualized historical mean** of the PIT returns matrix; **Σ = Ledoit-Wolf shrinkage** of the same returns, annualized (×252). Both from one PIT-bounded `daily_prices.adj_close` window. Score-derived expected-return views (feeding Black-Litterman) are a **later** story (Epic 9 / BL) — out of scope. Document the annualization factor and μ-source in the optimizer docstring so the assumption is auditable. [Source: `05` §1.3/§3; project rule #4 PIT]

### Scope boundaries (what is NOT this story)
- **Optimize API route** (`POST /portfolios/{id}/optimize`), constraints (de)serialization DTO, `infeasible` envelope handler, disclaimer → **QV-055**.
- **Risk-Parity / Min-Variance / Black-Litterman / HRP** optimizers and the solver/objective abstraction → QV-057 and later (framework expansion).
- **RiskEngine** metrics (beta/vol/drawdown/Sharpe/Sortino/HHI) → QV-058.
- **Rebalance** trades → QV-059. **Frontend** builder/optimize UI → QV-056.
- **Cardinality** (non-convex — needs MIQP/heuristics) and **turnover** enforcement inside the solve: model turnover if expressible as a convex constraint given `prior_weights`; treat cardinality as validate-only (via QV-053 `check()` post-solve) with a Dev-Notes flag — full cardinality-constrained optimization is a later enhancement, not this story.

### DAG & placement
`portfolio` sits above `market_data` in the import-linter DAG, so `portfolio/optimizer.py` may import the `market_data` returns reader — but prefer passing a `ReturnsMatrix` (`NDArray`) into the optimizer so it stays DB-agnostic and unit-testable with synthetic data. `covariance.py`/`optimizer.py` import only stdlib + numpy + cvxpy (+ QV-053 constraints, same context). No new cross-context edge → `lint-imports` stays 3/3. [Source: `backend/.importlinter`]

### References
- [Source: `plans/sprints/sprint-06-portfolio-i.md#QV-054`] — story + AC (MV, LW shrinkage, weights sum to 1, constraints respected, exp return/vol)
- [Source: `plans/05-domain-and-quant.md` §1.3 + §3] — `Optimizer.optimize(candidates, cov, exp_ret, constraints, as_of) -> Allocation`; shared constraints; shrinkage covariance
- [Source: `plans/09-roadmap-and-delivery.md` §5] — risk R7 (sample covariance instability)
- [Source: `plans/04-api-contracts.md` §3.5] — the optimize contract QV-055 will wire (per-constraint status, infeasible + binding constraint)
- [Source: `backend/src/quantvista/portfolio/constraints.py`] — QV-053 `Constraints`/`check`/`feasibility`/`InfeasibleConstraints`/`WEIGHT_SUM_EPSILON` to reuse
- [Source: `backend/src/quantvista/portfolio/interfaces.py`] — `IOptimizer` seam to refine
- [Source: `backend/src/quantvista/market_data/repositories.py`] — `daily_prices` access patterns to mirror for the returns reader
- [Source: `[[cvxpy-osqp-local-feasibility]]`] — verified install/solve on this box; `portfolio` extra + mypy override pattern
- [Source: `backend/pyproject.toml` lines 105–133] — optional-extra + mypy untyped-override precedents (`finbert`/`kafka`/`exchange_calendars`)

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- RED→GREEN per task: covariance / returns-reader / optimizer test suites each failed on the missing module, then passed after implementation.
- **SQL type-ambiguity** (`[[sql-type-ambiguity-at-source]]`): the returns reader's `(:start IS NULL OR date >= :start)` tripped `psycopg AmbiguousParameter` (can't type a NULL param) → fixed by building the `date >= :start` clause conditionally instead of binding a NULL.
- **OSQP can't take a quadratic constraint**: `quad_form(w,Σ) ≤ target_vol²` is a second-order-cone constraint → `SolverError` with OSQP → route those problems to **Clarabel** (bundled with cvxpy) while pure-QP objectives stay on OSQP.
- **mypy vs installed-but-untyped cvxpy**: locally cvxpy is installed (no stubs) so strict mypy followed it and errored on its dynamic attrs; in CI's quality job cvxpy is absent. Fixed with `follow_imports = "skip"` in the cvxpy/osqp mypy override so the strict run is identical either way.
- Gates: ruff + `ruff format` + mypy (strict, **227 files**) + `lint-imports` (3/3) all clean; full suite **571 passed / 5 skipped**; new-code coverage **97%** (covariance 100%, returns 98%, optimizer 96%).

### Completion Notes List

- **Technology choices shipped as agreed** (Deepak Sir, 2026-07-13): CVXPY+OSQP solver, hand-rolled NumPy Ledoit-Wolf, pluggable `CovarianceEstimator` Protocol. **Full solver/objective/problem framework deferred** and tracked in `deferred-work.md` (expands across Epic 7; QV-057 is the extraction point) — all CVXPY use is contained in `optimizer.py` so that refactor stays mechanical.
- **Ledoit-Wolf is bit-exact vs sklearn** — a faithful non-blocked reproduction of `sklearn.covariance.ledoit_wolf` (scaled-identity target), cross-checked to `1e-10` in a dev-only `pytest.importorskip("sklearn")` test. sklearn is **not** a prod or CI dependency, so that one cross-check skips in CI; the structural tests (symmetric/PSD/shrinkage-behavior) run everywhere. If we want CI to run the cross-check too, add `scikit-learn` to the `dev` extra (follow-up).
- **Dependency split:** `numpy` → **base** dependency (the `market_data` returns reader + covariance need it; lightweight/typed), while the heavy `cvxpy`/`osqp` solver → optional **`portfolio` extra**. `pyproject` mypy override for cvxpy/osqp uses `follow_imports = "skip"`. CI `backend-tests` job now installs `.[dev,portfolio]`; the DB-only job stays on `.[dev]` and the optimizer test `pytest.importorskip("cvxpy")`-skips at collection there.
- **max_sharpe** uses the convex y=κw homogenization (long-only), verified to dominate min_vol/target_return on Sharpe. **target_return** floor applies whenever set; **target_volatility** is a conic constraint (Clarabel). **Decimal↔float boundary**: solve in float64 → quantize to `Decimal(9,6)` → re-normalize Σw=1 (residual → largest) → validate via QV-053 `check()`; weights are `Decimal` on the wire.
- **Infeasible → binding (US-03):** structural `feasibility()` pre-check first; on a non-`optimal` solve, `_diagnose_infeasible` probes the tightest constraint (an LP for max achievable return → TARGET_RETURN; vol-cap → TARGET_VOLATILITY; else FULL_INVESTMENT), raising `InfeasibleConstraints` with the binding status.
- **Scope held:** no optimize API/route (QV-055), no risk-parity/BL/min-var (QV-057+), no RiskEngine (QV-058), no rebalance (QV-059), no FE (QV-056). `cardinality`/`turnover` in-solve deferred (cardinality is non-convex — MIQP); they remain validate-only via `check()`.

### File List

- Backend (impl): `src/quantvista/portfolio/covariance.py` (new), `src/quantvista/portfolio/optimizer.py` (new), `src/quantvista/market_data/returns.py` (new), `src/quantvista/portfolio/interfaces.py` (modified — typed `IOptimizer`), `pyproject.toml` (modified — `numpy` base dep, `portfolio` extra, cvxpy/osqp mypy override)
- Backend (tests): `tests/test_portfolio_covariance.py` (new), `tests/test_portfolio_optimizer.py` (new), `tests/integration/test_returns_matrix.py` (new)
- CI: `.github/workflows/ci.yml` (modified — `backend-tests` installs `.[dev,portfolio]`)

## Change Log

- QV-054 story drafted (ready-for-dev): CVXPY+OSQP mean-variance optimizer with hand-rolled NumPy Ledoit-Wolf shrinkage covariance behind a `CovarianceEstimator` Protocol, a PIT returns-matrix reader over `daily_prices.adj_close`, and a disciplined Decimal↔float boundary; reuses QV-053 `Constraints`/`check`/`feasibility`/`InfeasibleConstraints` and reports the binding constraint on infeasibility (US-03). `cvxpy`/`osqp` as an optional `portfolio` extra (verified installing+solving locally). Framework abstraction (solver/objective/subpackage tree) deferred — expands across Epic 7 by design.
- QV-054 implemented (review): `portfolio/covariance.py` (Protocol + Ledoit-Wolf bit-exact vs sklearn + sample baseline), `portfolio/optimizer.py` (`MeanVarianceOptimizer` min_vol/target_return/max_sharpe via CVXPY, OSQP + Clarabel for vol-cap, Decimal↔float round-trip, infeasible→binding diagnosis), `market_data/returns.py` (PIT returns-matrix reader), typed `IOptimizer`. `numpy` → base dep; `cvxpy`/`osqp` → `portfolio` extra; CI `backend-tests` installs it. 26 new tests; 571 passed / 5 skipped; new-code coverage 97%; all gates green. Full solver framework deferred → `deferred-work.md`.

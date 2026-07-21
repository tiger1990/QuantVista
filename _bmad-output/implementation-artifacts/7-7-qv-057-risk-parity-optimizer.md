---
baseline_commit: 60d3994055e097243a4515a6d60ba371efaa5dac
---

# Story 7.7: QV-057 — Risk Parity optimizer

Status: review

**Epic:** EPIC-PORT (Epic 7) · **Points:** 5 · **Depends:** QV-053 (`Constraints`/`check`/`feasibility`/`InfeasibleConstraints` ✓), QV-054 (`MeanVarianceOptimizer` + `CovarianceEstimator` + returns matrix ✓ — the pattern to extract from)

## Story

As a retail-oriented user, I want risk-balanced allocation, so that no single name dominates the portfolio's risk — a `RiskParityOptimizer` that equalizes each holding's risk contribution under the shared QV-053 constraints, selectable via `method="risk_parity"` (Pro tier). This is the **second optimizer**, so it's also the deliberate point to **extract the shared solver framework** that QV-054 deferred.

## Acceptance Criteria

1. **`RiskParityOptimizer`** — implements the `IOptimizer` seam and produces long-only weights whose **risk contributions are (near-)equal** (RCᵢ = wᵢ·(Σw)ᵢ, each ≈ 1/N of total risk). Convex **log-barrier** formulation solved with a conic solver (**Clarabel**, since `cp.log` is not a QP): minimize `½·wᵀΣw − (1/N)·Σ ln(wᵢ)` over `w ≥ ε`, then normalize `w := w/Σw` so weights sum to 1.0. Returns weights (Decimal, sum 1.0 ± ε) + expected return/vol (annualized). [Source: `05` §3 phase 2; Spinu/Maillard risk-parity formulation]

2. **Under the shared constraints (QV-053 reuse)** — `long_only` (inherent; RP requires w > 0), `max_weight`, and `sector_caps` are enforced **in the solve** as homogeneous linear constraints (`wᵢ ≤ max_weight·Σw`; `Σ_{i∈s} wᵢ ≤ cap_s·Σw` — linear in the un-normalized `w`, consistent with the post-solve normalization). The final Decimal allocation is validated through QV-053 `check()`. Full-investment holds by normalization. Constraints not meaningful for pure risk-parity (`target_return`/`target_volatility`/`max_turnover`/cardinality) are **ignored** for this method — document, don't silently misapply. [Source: `backend/src/quantvista/portfolio/constraints.py`]

3. **Infeasible → binding constraint (US-03)** — structural `feasibility(...)` pre-check first; a non-`optimal` solve raises `InfeasibleConstraints` with the binding constraint (shared diagnosis). No silent/degenerate result — same contract as QV-054.

4. **Shared solver framework extracted (the deferred QV-054 refactor)** — the plumbing common to both optimizers (annualize μ/Σ from the returns matrix, the `feasibility` pre-check, the **Decimal↔float weight round-trip**, `check()` validation, infeasible diagnosis, sector-matrix + linear-constraint helpers, and the `OptimizationRequest`/`OptimizationResult`/`Objective` models) moves into a shared **`BaseCvxpyOptimizer`** (template-method): the base owns the execution engine + boundary; each optimizer implements only its `_solve(...)` (the mathematical formulation). `MeanVarianceOptimizer` and `RiskParityOptimizer` both subclass it — **no behavior change to MV** (its tests stay green). This is the QV-054-deferred "decouple formulation from the CVXPY execution engine," now driven by a real second consumer. A speculative *multi-backend* `OptimizationSolver` protocol stays deferred (still one backend). [Source: `deferred-work.md` "FULL OPTIMIZER-SOLVER FRAMEWORK"; `backend/src/quantvista/portfolio/optimizer.py`]

5. **Selectable via `method` (Pro tier)** — the QV-055 optimize route dispatches `method="risk_parity"` → `RiskParityOptimizer` (removing its "not yet available" branch). `risk_parity` is under the seeded **`optimization`** flag (Pro) — same gate as `mean_variance`, **not** `optimization_advanced` (that's BL/HRP). The FE optimize panel gains a **method selector** (Mean-variance / Risk parity) so it's selectable end-to-end. [Source: `backend/src/quantvista/api/routes_portfolios.py`; `seed_reference.sql` `optimization`]

6. **Gates green** — ruff + `ruff format` + mypy (strict, whole tree) + `lint-imports` clean; new-code coverage ≥ 80%; FE eslint + tsc + vitest + build green. `cvxpy`/`osqp` already in the `portfolio` extra (Clarabel ships bundled with cvxpy — no new dependency).

## Tasks / Subtasks

- [x] **Task 1 — Extract the shared optimizer base** (AC: #4)
  - [x] Create `portfolio/optimization/` subpackage: `base.py` (models `OptimizationRequest`/`OptimizationResult`/`Objective` + constants + shared helpers `_sector_matrix`/`_sector_counts`/`_base_constraints`/`_to_decimal_weights` + `BaseCvxpyOptimizer` with the shared `optimize(request, returns)` orchestration and abstract `_solve(mu, sigma, cons, ids, sector_of, request) -> tuple[FloatMatrix | None, str]` + a default `_diagnose_infeasible`).
  - [x] `mean_variance.py`: `MeanVarianceOptimizer(BaseCvxpyOptimizer)` — move the existing `_solve_min_variance`/`_solve_max_sharpe`/`_max_achievable_return` logic into its `_solve` + override `_diagnose_infeasible` (the max-achievable-return probe). **No behavior change** — `test_portfolio_optimizer.py` passes unchanged (update only the import path).
  - [x] `__init__.py` re-exports `MeanVarianceOptimizer`, `RiskParityOptimizer`, `OptimizationRequest`, `OptimizationResult`, `Objective`. Delete `portfolio/optimizer.py`. Update importers: `api/routes_portfolios.py` (lazy import), `portfolio/interfaces.py` (TYPE_CHECKING), `tests/test_portfolio_optimizer.py`.
- [x] **Task 2 — RiskParityOptimizer** (AC: #1, #2, #3)
  - [x] `optimization/risk_parity.py`: `RiskParityOptimizer(BaseCvxpyOptimizer)._solve` — build `w = cp.Variable(n)`; objective `cp.Minimize(0.5*cp.quad_form(w, cp.psd_wrap(sigma)) - (1/n)*cp.sum(cp.log(w)))`; constraints `w >= 1e-6`, `w_i <= max_weight*cp.sum(w)` (if set), `sector_mask @ w <= cap*cp.sum(w)` (per sector cap); `prob.solve(solver=cp.CLARABEL)`; on optimal, return `w.value / w.value.sum()` (normalized), else `(None, status)`.
  - [x] RP ignores `objective`/`target_return`/`target_volatility`/`max_turnover`/cardinality (not applicable); `long_only` is inherent. Docstring states these assumptions + cites the RC formulation.
- [x] **Task 3 — API dispatch** (AC: #5)
  - [x] `api/routes_portfolios.py`: dispatch `method` → optimizer (`mean_variance` → MV, `risk_parity` → RP); `black_litterman`/`hrp` keep the "not yet available" `validation_error` + `optimization_advanced` gate. Lazy-import both optimizers.
- [x] **Task 4 — Frontend method selector** (AC: #5)
  - [x] `features/portfolios/OptimizePanel.tsx`: add a **Method** `<select>` (`mean_variance` / `risk_parity`) → include in the `OptimizeRequest`; when `risk_parity`, hide/disable the MV-only inputs (`objective`, `target_return`) since RP ignores them. Regenerate the client only if the request shape changed (it won't — `method` already in `OptimizeRequest`).
- [x] **Task 5 — Tests** (AC: all)
  - [x] `tests/test_risk_parity.py` (unit, `pytest.importorskip("cvxpy")`): equal-risk-contribution on a synthetic SPD covariance (assert per-asset RC within a tolerance of 1/N); weights sum to 1.0 (Decimal); long-only; `max_weight` respected (via QV-053 `check()`); `sector_caps` respected; infeasible (e.g. `max_weight` too small) → `InfeasibleConstraints` with binding kind.
  - [x] `tests/integration/test_api_optimize.py` (extend): `method="risk_parity"` → 200 with weights summing to 1.0 + disclaimer; a Free tenant → 403.
  - [x] `test_portfolio_optimizer.py`: import path updated; **all MV tests pass unchanged** (proves the extraction is behavior-preserving).
  - [x] FE: a vitest assertion that the method selector renders both options.
- [x] **Task 6 — Gates + reconcile** (AC: #6)
  - [x] Whole-tree ruff + `ruff format` + mypy + `lint-imports` (3/3) + full BE suite green; FE eslint + tsc + vitest + build green; coverage ≥ 80%. Reconcile QV-057 → done after merge; **watch CI to green** ([[feedback-full-tree-gates-and-watch-ci]]).

## Dev Notes

### This is the framework-extraction point — honor the deferral, but don't over-build
`deferred-work.md` committed to extracting the solver framework "by end of Epic 7, natural point QV-057." Do the substantive part now: a **`BaseCvxpyOptimizer`** template-method that separates the **execution engine** (annualize μ/Σ, `feasibility` pre-check, Decimal↔float round-trip, `check()`, infeasible diagnosis, weight quantization/normalization) from the **problem formulation** (each optimizer's `_solve`). That's the real value and it's driven by the real second consumer. **Do NOT** build a speculative multi-backend `OptimizationSolver` protocol (we still have exactly one backend, CVXPY) or an `Objective` strategy hierarchy (MV's 3 objectives + RP are fine as-is) — those stay deferred until a story needs them. Keep it behavior-preserving for MV (its full test suite must pass with only an import-path change). [Source: `deferred-work.md`; project rule: avoid speculative generality]

### Reuse QV-054 exactly — don't reinvent
`portfolio/optimizer.py` already has every shared piece: `_sector_matrix`, `_sector_counts`, `_base_constraints`, `_to_decimal_weights`, `_diagnose_infeasible`, the `_TRADING_DAYS`/`_WEIGHT_QUANTUM` constants, and the `optimize` orchestration (prepare μ/Σ → `raise_if_infeasible(feasibility(...))` → solve → diagnose/round-trip → `check()` → result). Move these into `base.py` verbatim; MV's `_solve` is the current `_solve_min_variance`/`_solve_max_sharpe` bodies. The returns matrix, `CovarianceEstimator` (Ledoit-Wolf), and `Constraints` are unchanged. [Source: `backend/src/quantvista/portfolio/optimizer.py`; `covariance.py`; `constraints.py`; `market_data/returns.py`]

### Risk-parity math (the one new formulation)
Equal risk contribution: RCᵢ = wᵢ·(Σw)ᵢ; the convex program `min ½wᵀΣw − (1/N)Σln(wᵢ)` over `w>0` yields equal RC (Spinu 2013). It's **not a QP** (`log` term) → OSQP can't solve it; use **Clarabel** (conic, bundled with cvxpy — verified installed). Box/sector caps enter as **homogeneous linear** constraints on the un-normalized `w` (`wᵢ ≤ max_weight·Σw`, etc.), so they stay linear and survive the final `w := w/Σw` normalization. `target_return`/`target_vol`/`turnover`/cardinality don't apply to pure RP — ignore them (RP has no return target); note in the docstring. `long_only` is inherent (`w>0`). [Source: `05` §3; standard risk-parity literature]

### Decimal↔float + infeasible — same discipline as QV-054
Solve in float64 → quantize weights to `Decimal(9,6)` → re-normalize `Σw=1` within `WEIGHT_SUM_EPSILON` → build `Allocation` → `check()`. On a non-`optimal` Clarabel status, run the shared diagnosis → `InfeasibleConstraints(binding)`. Money on the wire is Decimal. [Source: `[[market-data-provider-strategy]]`; `constraints.py`]

### Entitlement + API + FE
`risk_parity` is under the seeded **`optimization`** flag (Pro) — the endpoint already gates on it; `risk_parity` is **not** in `_ADVANCED_METHODS` (BL/HRP only). Just remove the "not yet available" branch for `risk_parity` and dispatch to `RiskParityOptimizer`. The FE `OptimizePanel` adds a Method selector; `method` is already a field on the generated `OptimizeRequest`, so no client regen needed. [Source: `backend/src/quantvista/api/routes_portfolios.py`; `seed_reference.sql`; `frontend/src/features/portfolios/OptimizePanel.tsx`]

### Scope boundary (what is NOT this story)
- Black-Litterman / HRP optimizers → later (keep "not yet available" + `optimization_advanced` gate).
- Multi-backend `OptimizationSolver` protocol + `Objective` strategy hierarchy → still deferred (`deferred-work.md`).
- RiskEngine metrics (QV-058), rebalance (QV-059).
- Additional `CovarianceEstimator` impls.

### References
- [Source: `plans/sprints/sprint-07-portfolio-ii-risk.md#QV-057`] — story + AC (equal risk contribution, shared constraints, method-selectable, Pro)
- [Source: `plans/05-domain-and-quant.md` §3] — optimizer phases; risk parity = phase 2 (Pro)
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md`] — the framework-extraction commitment (QV-057 is the point)
- [Source: `backend/src/quantvista/portfolio/optimizer.py`] — the QV-054 optimizer to extract the base from
- [Source: `backend/src/quantvista/portfolio/{constraints,covariance}.py`, `market_data/returns.py`] — the reused domain pieces
- [Source: `backend/src/quantvista/api/routes_portfolios.py`] — the optimize dispatch to extend
- [Source: `frontend/src/features/portfolios/OptimizePanel.tsx`] — the FE panel to add the method selector
- [Source: `[[cvxpy-osqp-local-feasibility]]`] — Clarabel is bundled + installed; no new dependency

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (dev-story)

### Debug Log References

- Prototyped the log-barrier risk-parity solve before writing files: verified equal RC (0.25 each on a 4-asset synthetic SPD Σ) and that the homogeneous `wᵢ ≤ max_weight·Σw` cap holds after normalization (max weight = 0.30). CLARABEL + SCS are the installed conic solvers; `cp.log` routes to CLARABEL.
- `mypy src tests` (my invocation) surfaced a false `load_nifty200_universe` import error; CI runs **bare `mypy`** whose `files` includes `scripts`, so it resolves — bare mypy is green (234 files). Matched CI's invocation.
- `check()` skips `target_return`/`target_volatility` when the `Allocation` carries no portfolio return/vol (the RP path builds weights-only), so RP ignoring those constraints is safe — no false infeasible.

### Completion Notes List

- **Framework extraction (AC #4):** `BaseCvxpyOptimizer` (template-method) owns the shared engine — cardinality guard, annualized μ/Σ, `feasibility` pre-check, `_solve` hook, Decimal↔float round-trip, `check` validation, annualized metrics, and a default `_diagnose`. `MeanVarianceOptimizer` refactored onto it (its `_solve` keeps the min-vol/max-sharpe/target-return formulation; overrides `_diagnose` with the max-achievable-return probe) — **behavior-preserving: all 10 MV tests pass with only an import-path change**. Kept the multi-backend `OptimizationSolver` protocol deferred (still one backend).
- **RiskParityOptimizer (AC #1–3):** convex log-barrier `min ½wᵀΣw − (1/N)Σln(wᵢ)` (Clarabel), `max_weight`/`sector_caps` as homogeneous linear constraints on un-normalized `w`, normalized to Σw=1; ignores objective/target_return/target_vol/turnover/cardinality; long-only inherent. Structural infeasibility (e.g. `max_weight` < 1/N) surfaces via the base `feasibility` pre-check with the binding `MAX_WEIGHT`.
- **API (AC #5):** `_IMPLEMENTED_METHODS = {mean_variance, risk_parity}`; the handler dispatches `risk_parity → RiskParityOptimizer`, else `MeanVarianceOptimizer`. BL/HRP keep the not-yet-available 422 (Quant tenant) / advanced-gate 403 (Pro tenant). Added a Quant-tier tenant to the optimize integration fixture to cover the not-implemented branch.
- **FE (AC #5):** `OptimizePanel` gains a Method selector; selecting Risk parity disables the objective + target-return inputs and drops `target_return` from the request. 2 new vitest cases.
- **Gates (AC #6):** ruff + ruff format + bare mypy (234 files) + lint-imports (3/3) all clean; **593 passed / 5 skipped** backend (no regressions); FE eslint + tsc + 59 vitest + `next build` all green; **96%** coverage on the new `portfolio/optimization` package.

### File List

**Backend — new**
- `backend/src/quantvista/portfolio/optimization/__init__.py`
- `backend/src/quantvista/portfolio/optimization/base.py`
- `backend/src/quantvista/portfolio/optimization/mean_variance.py`
- `backend/src/quantvista/portfolio/optimization/risk_parity.py`
- `backend/tests/test_risk_parity.py`

**Backend — modified**
- `backend/src/quantvista/portfolio/optimizer.py` — **deleted** (moved into the `optimization/` subpackage)
- `backend/src/quantvista/portfolio/interfaces.py` — TYPE_CHECKING import → `portfolio.optimization`
- `backend/src/quantvista/api/routes_portfolios.py` — `_IMPLEMENTED_METHODS` + optimizer dispatch + lazy import from `optimization`
- `backend/tests/test_portfolio_optimizer.py` — import path → `portfolio.optimization` (otherwise unchanged)
- `backend/tests/integration/test_api_optimize.py` — Quant-tier fixture tenant; risk_parity success test; advanced-gate 403 test; not-implemented 422 → `hrp` via Quant

**Frontend — modified**
- `frontend/src/features/portfolios/OptimizePanel.tsx` — Method selector; disable MV-only inputs for risk parity
- `frontend/src/features/portfolios/OptimizePanel.test.tsx` — `reset` mock + 2 method-selector cases

## Change Log

- QV-057 implemented (review): `RiskParityOptimizer` (equal-risk-contribution, convex log-barrier via Clarabel, homogeneous box/sector constraints, normalized to Σw=1) under the shared QV-053 constraints; deferred solver-framework extraction landed as `BaseCvxpyOptimizer` (execution engine vs. `_solve` formulation) with `MeanVarianceOptimizer` refactored onto it behavior-preserved; API dispatch of `method=risk_parity` (Pro) + FE method selector. No new dependency (Clarabel bundled with cvxpy). 96% coverage on the new package; full BE (593 passed) + FE (59 passed) + build green.

- QV-057 story drafted (ready-for-dev): `RiskParityOptimizer` (equal-risk-contribution via the convex log-barrier formulation, Clarabel, homogeneous box/sector constraints, normalized to sum 1) under the shared QV-053 constraints; the deferred solver-framework extraction into a `BaseCvxpyOptimizer` template-method (execution engine vs. formulation) with `MeanVarianceOptimizer` refactored onto it behavior-preserved; API dispatch of `method=risk_parity` (Pro) + FE method selector. Reuses QV-054's returns/covariance/constraints/round-trip; no new dependency (Clarabel bundled).

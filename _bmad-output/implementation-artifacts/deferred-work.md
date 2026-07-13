# Deferred Work

Tracks items deferred during code review that are real but not actionable in the current story.

---

## Deferred from: code review of 7-2-qv-052-portfolio-crud-api (2026-07-13)

- **TOCTOU in `idempotent()`**: Both concurrent `produce()` calls execute before the UNIQUE guard fires; the rollback is correct for DB-only side effects, but if a future caller of `idempotent()` has external side effects (email, webhooks), duplicates are possible. Document constraint in `api/idempotency.py` docstring and address when adopting for alerts/screens routes.
- **Quota race on `POST /portfolios`**: `count_portfolios` + `enforce_portfolio_limit` is not serializable under concurrent creates. Two requests from the same Free-tier tenant can both read count=0, both pass, both insert — exceeding the quota by 1. Fix requires `SELECT count(*) FOR UPDATE` or a `SERIALIZABLE` transaction. Defer to a hardening sprint.
- **No TTL/expiry on `idempotency_keys`**: The table grows without bound. Add an `expires_at` column and a pg_cron cleanup job (or APScheduler beat task) before the table exceeds millions of rows in production.
- **Session rollback model**: `idempotent()` issues `session.rollback()` after `IntegrityError`; correctness depends on the calling session using `autocommit=False` (standard SQLAlchemy). This is true today but should be documented in the helper's docstring.
- **`p['target_weight']` psycopg type coercion**: The `cast()` in `routes_portfolios.py` is a mypy cast only. If psycopg ever returns NUMERIC as `str` instead of `Decimal`, the weight sum would be computed over strings. Confirm driver config + add an explicit `Decimal(str(v))` coercion if driver behavior changes.

---

## Deferred from: QV-054 architecture decision (2026-07-13) — FULL OPTIMIZER-SOLVER FRAMEWORK

**Owner/status:** deliberately deferred by Deepak Sir + Claude. **Must be fully in place by the END of Epic 7** (before Epic 7 retrospective). A teammate can pick up any bullet below. This is NOT a bug — it's a planned, staged expansion (YAGNI now; extract when a real second consumer exists).

**Why deferred:** QV-054 ships the *technology choices* (CVXPY+OSQP solver, hand-rolled NumPy Ledoit-Wolf, optional `portfolio` extra) and only the one seam with a real second consumer today — the `CovarianceEstimator` Protocol. Building the full framework in QV-054 would be speculative generality against stories that don't exist yet (project rule: *avoid speculative generality; refactor when the pressure is real*). QV-054 keeps all CVXPY usage contained in `portfolio/optimizer.py` so the extraction below is mechanical.

**What QV-054 intentionally does NOT build (build across QV-055 → QV-059, done by end of Epic 7):**
- **`OptimizationSolver` / `OptimizationProblem` abstraction** — decouple the optimizer's mathematical formulation from the CVXPY execution engine (`MeanVarianceOptimizer → OptimizationProblem → CVXPYSolver(OSQP) → OptimizationResult`). **Natural extraction point: QV-057 (Risk Parity)** — the first real second optimizer creates the pressure. Enables comparing/swapping solver backends without touching optimizer logic.
- **`Objective` strategy hierarchy** (`Variance`/`Sharpe`/`MinVol`/… swappable) — QV-054 handles `min_vol`/`target_return`/`max_sharpe` as enum branches inside one optimizer; promote to strategies when CVaR / tracking-error / max-diversification objectives land.
- **Optimizer subpackage tree** — grow `portfolio/{covariance,optimizers,solvers}/…` (and, if it reads cleaner, a `domain/` for the Protocols) **only as real files appear**. Do NOT relocate the already-merged flat `portfolio/constraints.py` (QV-053) or pre-create placeholder files for unwritten optimizers.
- **Additional `CovarianceEstimator` impls** (OAS, EWMA, factor-model, Graphical Lasso) — the Protocol ships in QV-054 with `LedoitWolf` (+ `Sample` baseline); add estimators when a story needs them.
- **Second solver backend** (Clarabel/SCS explicit) + **`SolverConfig`** tuning object + **richer `OptimizationResult` telemetry** (iterations, solve_time, solver name) — add when there's a real need to tune/compare.

**End-of-Epic-7 acceptance (for the teammate):** by the Epic 7 retrospective, the optimizer family (MV / Risk-Parity / at least the seam for BL/HRP) runs through a shared `OptimizationSolver` abstraction with pluggable `CovarianceEstimator` and `Objective`, and no optimizer imports CVXPY directly except the solver adapter. Cross-ref: `[[cvxpy-osqp-local-feasibility]]`, QV-054 story Dev Notes ("Framework expansion is deferred on purpose"), QV-057/058/059 stories.

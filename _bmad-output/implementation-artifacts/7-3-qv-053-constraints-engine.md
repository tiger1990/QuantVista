---
baseline_commit: 0eaf451c3ede8196b97d92029ce915b9e5c58ea4
---

# Story 7.3: QV-053 — Constraints engine

Status: done

**Epic:** EPIC-PORT (Epic 7) · **Points:** 5 · **Depends:** — (none; this is the shared primitive the optimizers build on)

## Story

As a quant, I want a shared, optimizer-agnostic constraints model, so that every optimizer (Mean-Variance QV-054, Risk-Parity QV-057, HRP/Black-Litterman later) and the backtester honor the **same** allocation rules — and an infeasible problem names its **binding constraint** instead of failing silently or returning a nonsense allocation (US-03).

## Acceptance Criteria

1. **`Constraints` value object** — an immutable (frozen) model capturing the full constraint set from `05` §3 and the `04` §3.5 optimize contract:
   - `max_weight` (per-name cap ∈ (0, 1]), `min_weight` (per-name floor, default 0),
   - `long_only` (bool, default `True` → every weight ≥ 0),
   - `sector_caps` (`dict[str, Decimal]`: sector → max aggregate weight),
   - `cardinality_min` / `cardinality_max` (int | None: count of non-zero holdings),
   - `target_volatility` / `target_return` (Decimal | None: optimizer targets, validated as ceilings/floors here),
   - `max_turnover` (Decimal | None: one-way turnover `Σ|wᵢ − wᵢ_prev| / 2 ≤ limit`).
   - Full-investment (`Σw = 1 ± ε`) is an **always-on** invariant, not an optional field.
   - All money/weight fields are `Decimal`, never `float`. Field-level bounds validated at construction (e.g. `max_weight ∈ (0,1]`, `cardinality_min ≥ 1`, caps ∈ (0,1]).

2. **Allocation validation** — `check(constraints, allocation) -> ConstraintReport` evaluates a **candidate allocation** against every constraint and returns a **per-constraint status** (mirrors the API's "per-constraint status", `04` §3.5 line 123). Each status carries: constraint `kind`, `satisfied: bool`, human-readable `detail`, and a signed `slack` (room remaining if satisfied / magnitude of violation if not). `feasible` is the AND of all statuses.

3. **Binding constraint on infeasibility (US-03)** — when ≥1 constraint is violated, the report identifies exactly one **`binding`** constraint = the **most-violated** by normalized violation magnitude, with a **deterministic** tie-break by a fixed constraint-priority order (so the same infeasible input always names the same constraint — the message must be reproducible for tests and the UI). No silent failure, no `None` allocation without a binding reason.

4. **Structural feasibility pre-check** — `feasibility(constraints, universe_size, sector_universe) -> ConstraintReport` detects a constraint set that is **unsatisfiable before any optimizer runs** (e.g. `cardinality_min > universe_size`; `max_weight × cardinality_max < 1` so full investment is impossible; a `min_weight × cardinality_min > 1`; a `long_only` + full-investment contradiction; sector caps that cannot sum to 1 over the available sectors). Returns the same `ConstraintReport` shape with the binding structural constraint. Targets that require expected-returns/covariance (`target_return` reachability) are **out of scope here** — those are validated by the optimizer (QV-054) which has Σ and μ.

5. **`InfeasibleConstraints` exception** — defined in this module, carrying the binding `ConstraintStatus`, so consumers (the QV-055 optimize API) can map it to the canonical `error.code = "infeasible"` (422) with the binding constraint in the message. The engine itself is pure-domain: `check`/`feasibility` **return** reports; a thin `raise_if_infeasible(report)` helper raises `InfeasibleConstraints` for callers that prefer control-flow. No FastAPI, no HTTP status codes in this module.

6. **Pure domain, no I/O** — lives in the `portfolio` bounded context, imports only stdlib + `Decimal` (no DB, no session, no API, no migration, no new dependency). Unit-testable without a database — mirrors QV-051's pure `enforce_portfolio_limit` guard. `lint-imports` stays green (no new cross-context edge). Coverage ≥ 80% on new code (target 100% — it's pure logic).

## Tasks / Subtasks

- [x] **Task 1 — `Constraints` value object + field validation** (AC: #1)
  - [x] `portfolio/constraints.py`: frozen `@dataclass(frozen=True)` `Constraints` with all fields above, `Decimal` typed, `X | None` for optionals, `sector_caps` defaulting to an empty mapping (use `field(default_factory=dict)` and copy to a read-only view / `MappingProxyType` to preserve immutability).
  - [x] `__post_init__` validates field bounds and raises `ValueError` on nonsense (e.g. `max_weight ∉ (0,1]`, `cardinality_min < 1`, `cardinality_min > cardinality_max`, a `sector_caps` value ∉ (0,1], negative `max_turnover`, `min_weight > max_weight`). Keep messages specific.
  - [x] `WEIGHT_SUM_EPSILON` for the `Σw = 1` tolerance — **reuse the constant already in `portfolio/services.py`** (`Decimal("0.0001")`) rather than redefining; import it (or lift it to a shared `portfolio/_constants.py` if that reads cleaner — dev's call, but do not define two different epsilons).
- [x] **Task 2 — Report types** (AC: #2, #3)
  - [x] `ConstraintKind` (`Enum`): `MAX_WEIGHT`, `MIN_WEIGHT`, `LONG_ONLY`, `SECTOR_CAP`, `CARDINALITY`, `TARGET_VOLATILITY`, `TARGET_RETURN`, `TURNOVER`, `FULL_INVESTMENT`. The enum's declaration order **is** the deterministic tie-break priority (document this).
  - [x] Frozen `ConstraintStatus {kind, satisfied, detail, slack: Decimal | None}` and frozen `ConstraintReport {feasible: bool, statuses: tuple[ConstraintStatus, ...], binding: ConstraintStatus | None}`. `binding is None` iff `feasible`.
- [x] **Task 3 — `Allocation` input + `check()`** (AC: #2, #3)
  - [x] `Allocation` value object: `weights: Mapping[UUID, Decimal]`, `sector_of: Mapping[UUID, str]`, optional `prior_weights: Mapping[UUID, Decimal] | None` (for turnover), optional `portfolio_volatility` / `portfolio_return: Decimal | None` (for target checks — when `None`, the corresponding target status is **skipped/not-applicable**, not failed).
  - [x] `check(constraints, allocation) -> ConstraintReport`: evaluate each active constraint → `ConstraintStatus`. Non-zero holding = weight strictly > 0 (respect epsilon). Sector cap aggregates weights by `sector_of`. Turnover uses one-way `Σ|Δw|/2`. Compute signed `slack` consistently (positive = satisfied room, negative = violation size), normalized per constraint so cross-kind comparison for `binding` is fair (e.g. violation ÷ limit).
  - [x] `binding` = the violated status with the most-negative normalized slack; ties broken by `ConstraintKind` declaration order. Deterministic and total.
- [x] **Task 4 — `feasibility()` structural pre-check** (AC: #4)
  - [x] `feasibility(constraints, universe_size: int, sector_universe: Mapping[str, int]) -> ConstraintReport` implementing the structural checks in AC #4. No μ/Σ dependence. Same report shape + binding selection.
- [x] **Task 5 — `InfeasibleConstraints` + helper** (AC: #5)
  - [x] `class InfeasibleConstraints(Exception)` carrying `binding: ConstraintStatus` and a message built from `binding.detail`. `raise_if_infeasible(report) -> None` raises it when `not report.feasible`. **No** mapping to HTTP here — that wiring belongs to QV-055 (note it in Dev Notes as a forward hook, do not implement the route).
  - [x] Export the public surface via `__all__`: `Constraints`, `Allocation`, `ConstraintKind`, `ConstraintStatus`, `ConstraintReport`, `InfeasibleConstraints`, `check`, `feasibility`, `raise_if_infeasible`.
- [x] **Task 6 — Tests** (AC: all)
  - [x] `tests/test_portfolio_constraints.py` (unit, no DB): construction validation (each bad field raises `ValueError`); every constraint's satisfied **and** violated path; full-investment tolerance at ±ε boundary; long-only vs a negative weight; sector cap aggregation across multiple names; cardinality min/max at boundaries; turnover with and without `prior_weights`; target vol/return skipped when the metric is `None`; **binding selection determinism** (multiple violations → the documented most-violated/priority winner, asserted exactly); `feasibility` structural cases (`cardinality_min > universe_size`, `max_weight × cardinality_max < 1`, sector caps under-sum); `raise_if_infeasible` raises/does-not-raise; `InfeasibleConstraints.binding` round-trips.
  - [x] AAA structure, behavior-named tests (project testing rule). Target 100% line coverage on `constraints.py`.
- [x] **Task 7 — Gates + reconcile** (AC: #6)
  - [x] `ruff check` + `ruff format` + `mypy` (strict on the new public API) + `lint-imports` (3/3 contracts hold — no new cross-context import) all clean; full suite green; new-code coverage ≥ 80%.
  - [x] Reconcile QV-053 → done in sprint-status after merge (per the branch/PR rhythm).

## Dev Notes

### This story is PURE DOMAIN — no DB, no API, no migration, no dependency
QV-053 is the `[QUANT]` primitive the whole optimizer family stands on. It is **weights-and-rules logic only** (`Decimal` arithmetic, dict aggregation, comparisons). It deliberately does **not** touch: the DB/session, FastAPI, the entitlements service, or any matrix library. Model it exactly like QV-051's `enforce_portfolio_limit` / `validate_position_weights` in `portfolio/services.py` — pure functions/value-objects that unit-test without a session. [Source: `backend/src/quantvista/portfolio/services.py`; `[[forward-declared-schema-migrations]]` — nothing to migrate here]

### ⚠️ No numpy/scipy/cvxpy in this repo — and QV-053 must NOT add them
`backend/pyproject.toml` ships **only `polars`** for numerics (no numpy, scipy, or cvxpy). The constraints engine needs none of them — it's scalar `Decimal` work. **Do not add a math dependency in this story.** The matrix optimizer (QV-054, Ledoit-Wolf covariance + QP solve) is where numpy/scipy (or cvxpy) gets introduced, with a justification comment in `pyproject.toml` following the existing per-story dependency-comment convention (see the `exchange-calendars`/`polars` comments). [Source: `backend/pyproject.toml` lines 12–41]

### Where it lives + the DAG
`portfolio/constraints.py` (new, single focused module, ~200–350 lines). `portfolio` sits **above** `analytics` and imports only lower layers/stdlib — a pure constraints module imports **nothing** from other contexts, so all three `import-linter` contracts stay green with no config change. Don't scatter this into `analytics`; `05` §1.3 places `Optimizer`/`RiskEngine`/`PortfolioService` in the **Portfolio & risk** context, and `portfolio/interfaces.py` already declares `IOptimizer`. [Source: `backend/.importlinter`; `plans/05-domain-and-quant.md` §1.3; `backend/src/quantvista/portfolio/interfaces.py`]

### The existing interface seam to honor (don't reinvent, don't break)
`portfolio/interfaces.py` already declares `IOptimizer.optimize(spec) -> dict[UUID, Decimal]` and notes *"Infeasible problems raise/return the binding constraint, never a silent result."* The domain plan §1.3 sketches the richer `Optimizer.optimize(candidates, cov, exp_ret, constraints: Constraints, as_of) -> Allocation`. QV-053 supplies the **`Constraints`** type that signature refers to. Keep `Constraints` optimizer-agnostic — it must serve mean-variance, risk-parity, HRP, and the backtester (QV-064) unchanged. Do **not** modify `IOptimizer` in this story (that's QV-054's job); just make `Constraints` importable and ready. [Source: `backend/src/quantvista/portfolio/interfaces.py`; `plans/05-domain-and-quant.md` §1.3 lines 63–79]

### Money & typing (locked project rules)
`Decimal`/`NUMERIC` for every weight and target — **never `float`** (project rule #9 / money rule). `from __future__ import annotations`, modern typing (`X | None`, `list[...]`, `Mapping[...]`), full type coverage for mypy. Immutability is a hard rule — frozen dataclasses, no in-place mutation of inputs; when copying `sector_caps`/`weights` defensively, produce new read-only mappings. [Source: `_bmad-output/project-context.md` §Language-Specific; `[[market-data-provider-strategy]]` money rule]

### The API contract this feeds (context only — NOT built here)
`POST /portfolios/{id}/optimize` (`04` §3.5) sends `constraints: { max_weight, sector_caps, target_volatility, long_only, ... }` and expects **success → weights summing to 1.0 + per-constraint status**, **infeasible → `error.code="infeasible"` (422) + the binding constraint** (US-03 AC). QV-053 produces the domain objects (`Constraints`, `ConstraintReport`, `InfeasibleConstraints`) that QV-055 will serialize/deserialize and map to that envelope. The JSON⇆`Constraints` (de)serialization DTO and the exception→`infeasible`-envelope handler are **QV-055 scope** — leave a one-line forward-hook note, don't implement them. [Source: `plans/04-api-contracts.md` §3.5 lines 115–125; `plans/01-prd.md` US-03 lines 100–102]

### Binding-constraint determinism (the crux of US-03)
"Clear infeasibility message" (US-03 AC) means the **same infeasible input must always name the same binding constraint** — otherwise the UI copy and the tests are non-deterministic. Implement `binding` as: among violated statuses, pick the most-negative **normalized** slack (violation ÷ the constraint's own limit, so a 5%-over max-weight and a 5%-over sector-cap compare fairly); break exact ties by `ConstraintKind` **declaration order**. Assert this exact winner in tests with a multi-violation fixture. [Source: `plans/01-prd.md` US-03; `plans/05-domain-and-quant.md` §3 lines 120–121]

### Scope boundary (what is NOT this story)
- The **optimizer math** (covariance, expected returns, QP/convex solve, `max_sharpe`/`min_vol`/target-return objectives) → QV-054. `target_return` *reachability* (needs μ) is validated there, not here.
- The **optimize API route**, the constraints (de)serialization DTO, and the `infeasible`-envelope handler → QV-055.
- **Risk-parity** consumption of `Constraints` → QV-057. **Backtest** consumption → QV-064.
- Any DB table, migration, or entitlement wiring. (Constraints are computed, not stored.)

### References
- [Source: `plans/sprints/sprint-06-portfolio-i.md#QV-053`] — story + AC (shared constraints; binding constraint on infeasible; `05` §3)
- [Source: `plans/05-domain-and-quant.md` §1.3 + §3] — `Optimizer`/`Constraints` sketch; "Constraints engine is shared across optimizers … Infeasible problems return the binding constraint, not a silent failure."
- [Source: `plans/04-api-contracts.md` §3.5 lines 115–125] — optimize request `constraints{}`, per-constraint status, `infeasible` (422) + binding constraint
- [Source: `plans/01-prd.md` US-03 lines 100–102] — "constraints respected or a clear infeasibility message"
- [Source: `backend/src/quantvista/portfolio/interfaces.py`] — `IOptimizer` seam ("never a silent result")
- [Source: `backend/src/quantvista/portfolio/services.py`] — the pure-guard pattern (`enforce_portfolio_limit`, `validate_position_weights`, `WEIGHT_SUM_EPSILON`) to mirror and reuse
- [Source: `backend/.importlinter`] — DAG: `portfolio` above `analytics`; pure module keeps all 3 contracts green
- [Source: `backend/pyproject.toml` lines 12–41] — no numpy/scipy/cvxpy; add none in this story

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- RED→GREEN: `test_portfolio_constraints.py` (49 tests) failed on `ModuleNotFoundError: quantvista.portfolio.constraints`; passed after implementing the module.
- Coverage started at 99% (2 validation branches unhit: `min_weight ∉ [0,1]`, `cardinality_max < 1`) → added `test_min_weight_out_of_range_raises` + `test_cardinality_max_below_one_raises` → **100%**.
- Gates: ruff + `ruff format` clean; mypy clean (1 source file, no issues); `lint-imports` **3/3 KEPT** (116 files, 271 deps); full unit suite **357 passed / 4 skipped** (308 prior + 49 new, zero regressions).

### Completion Notes List

- **Pure domain, zero new surface.** `portfolio/constraints.py` imports only stdlib + `Decimal` + the existing `WEIGHT_SUM_EPSILON` from `portfolio.services` (reused, not redefined — per Task 1). No DB, session, API, migration, or dependency. This story adds **no integration/API footprint**, so the DB-backed integration suite is structurally unaffected; the non-integration full suite is the relevant regression gate.
- **`Constraints` / `Allocation` are frozen + defensively copied.** `__post_init__` validates every field bound (raises `ValueError`) and re-wraps `sector_caps`/`weights`/`sector_of`/`prior_weights` in `MappingProxyType` so a caller mutating the source dict can't leak in — immutability is a hard project rule.
- **Binding-constraint determinism (US-03).** `_pick_binding` selects the most-negative **normalized** slack (violation ÷ limit magnitude, so cross-kind violations compare fairly), tie-broken by `ConstraintKind` **declaration order**. Same infeasible input → same binding constraint, asserted in `test_binding_selection_is_deterministic` and `test_binding_is_most_violated`.
- **Active-constraint model.** Only active constraints emit a `ConstraintStatus`: turnover is skipped without `prior_weights`; target vol/return are skipped when the portfolio metric is `None` (not failed); `long_only`/`min_weight` only emit when enabled. `FULL_INVESTMENT` and (when weights present) any set field always emit.
- **`check` vs `feasibility`.** `check` validates a candidate allocation; `feasibility` is the structural pre-check (cardinality vs universe, max_weight reachability, min_weight×cardinality over-allocation, all-capped sectors under-summing) with **no μ/Σ dependence** — `target_return` reachability is deferred to QV-054.
- **Forward hooks (not built here):** `InfeasibleConstraints` + `raise_if_infeasible` are ready for QV-055 to map to `error.code="infeasible"` (422); `Constraints` is ready for QV-054's `Optimizer.optimize(..., constraints, ...)`. `IOptimizer` left untouched.
- **Money as `Decimal` throughout.** No `float` anywhere; slack/normalization all `Decimal`.

### File List

- Backend (impl): `src/quantvista/portfolio/constraints.py` (new)
- Backend (tests): `tests/test_portfolio_constraints.py` (new — 49 unit tests, 100% coverage of the module)

## Change Log

- QV-053 story drafted (ready-for-dev): a pure-domain, optimizer-agnostic constraints engine in `portfolio/constraints.py` — `Constraints` value object, `check()`/`feasibility()` returning a per-constraint `ConstraintReport`, deterministic **binding-constraint** selection on infeasibility (US-03), and an `InfeasibleConstraints` exception for the future optimize API. No DB/API/migration/dependency; unit-tested only; mirrors QV-051's pure-guard pattern.
- QV-053 implemented (review): `portfolio/constraints.py` (`Constraints`/`Allocation`/`ConstraintKind`/`ConstraintStatus`/`ConstraintReport`/`InfeasibleConstraints` + `check`/`feasibility`/`raise_if_infeasible`), reusing `WEIGHT_SUM_EPSILON`. 49 unit tests, 100% module coverage; ruff/format/mypy clean; `lint-imports` 3/3 KEPT; 357 passed / 4 skipped, zero regressions. No new dependency (numpy/scipy deferred to QV-054).

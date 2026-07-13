---
baseline_commit: 02c525accb19e9010c6e855b851c6954b93cca9b
---

# Story 7.5: QV-055 — Optimize API

Status: review

**Epic:** EPIC-PORT (Epic 7) · **Points:** 3 · **Depends:** QV-054 (`MeanVarianceOptimizer` + `returns_matrix_as_of` ✓ done), QV-052 (portfolio CRUD + positions ✓ done)

## Story

As a user, I want to optimize a portfolio via the API, so that I get allocation weights under my chosen method/objective/constraints — success returns weights + metrics + per-constraint status; an infeasible problem returns `error.code="infeasible"` with the binding constraint (US-03); and the research-not-advice disclaimer rides every response.

## Acceptance Criteria

1. **`POST /api/v1/portfolios/{id}/optimize`** — body `{ method, objective, constraints{}, candidate_universe, risk_free_rate? }` (04 §3.5). Tenant-scoped: a portfolio that isn't the caller's is **404** (RLS-invisible, never a 403 that leaks existence). Wires the QV-054 optimizer: resolve the candidate universe → build the PIT returns matrix → `MeanVarianceOptimizer.optimize(...)`. Uses the standard `Envelope`. [Source: `plans/04-api-contracts.md` §3.5]

2. **Constraints (de)serialization DTO** — a Pydantic `OptimizeConstraints` (all money/weights `Decimal`, `[0,1]` bounds at the edge) that maps to QV-053's `Constraints` value object (`to_domain()`), plus `objective ∈ {max_sharpe, min_vol, target_return}` and `method ∈ {mean_variance, risk_parity, black_litterman, hrp}`. This is the JSON⇆`Constraints` boundary QV-053/054 deferred to this story. `sector_caps` is `dict[str, Decimal]`.

3. **Entitlement + method/tier gating (US-06)** — the endpoint requires the seeded **`optimization`** flag → **403 `entitlement_exceeded`** on Free (which has `optimization=false`). `black_litterman`/`hrp` additionally require **`optimization_advanced`** (Quant) → 403 if absent. Only **`mean_variance`** is implemented now; any other method returns **422 `validation_error`** ("method not yet available") — `risk_parity` arrives QV-057, BL/HRP later. Do **not** reinvent the entitlement check — use `EntitlementService.check(tenant_id, "optimization")`. [Source: `backend/src/quantvista/db/seeds/seed_reference.sql` lines 56–57, 77–78; `04` §3.5 "method gated by tier/phase"]

4. **Infeasible → binding constraint (US-03)** — `MeanVarianceOptimizer` raises `InfeasibleConstraints` (structural pre-check or non-optimal solve); a new app-level exception handler maps it to **`error.code="infeasible"` (422)** with the binding constraint's detail in the message. No silent failure. (`infeasible` is already in `ERROR_STATUS`.) [Source: `backend/src/quantvista/schemas/envelope.py` line 27; `backend/src/quantvista/portfolio/optimizer.py`]

5. **Research-not-advice disclaimer (locked decision D1)** — success responses carry the **`X-QuantVista-Disclaimer`** header **and** a `meta.disclaimer` field, reusing the existing `DISCLAIMER` / `_with_disclaimer` helper (do not invent a new string). Optimization output is a research signal — never "buy X". [Source: `backend/src/quantvista/api/routes_stocks.py` lines 26–41; `04` §compliance header; project rule #7]

6. **PIT + candidate universe** — `candidate_universe="current_positions"` resolves to the portfolio's position `stock_id`s (`list_positions`); the returns matrix is built as of the **latest available price date** (`latest_price_date`, PIT `date <= as_of` — no look-ahead, rule #4); `sector_of` for sector caps is read from `stocks.sector`. An empty/too-thin universe surfaces a clear error (not a crash). Optimize is a **pure computation** here — it does **not** persist an `optimization_runs` row (that's QV-058/later), so no `Idempotency-Key` handling is needed.

7. **Gates green** — ruff + `ruff format` + mypy (strict, whole tree) + `lint-imports` clean; the route registered with its handler; new-code coverage ≥ 80%. The optimizer import path pulls `cvxpy` (the `portfolio` extra) — the **integration test** for this endpoint therefore runs in the `backend-tests`/local envs where `[portfolio]` is installed; guard collection with `pytest.importorskip("cvxpy")` so the DB-only CI job (which lacks the extra) skips it cleanly, exactly like `test_portfolio_optimizer.py`.

## Tasks / Subtasks

- [x] **Task 1 — Wire DTOs** (AC: #2)
  - [x] `schemas/optimize.py`: `OptimizeConstraints` (Pydantic v2, `Decimal | None` fields with `ge/le`; `long_only: bool = True`; `sector_caps: dict[str, Decimal]`) + `to_domain() -> Constraints`; `OptimizeRequest {method: Literal[...], objective: Literal["max_sharpe","min_vol","target_return"], constraints: OptimizeConstraints, candidate_universe: Literal["current_positions"] = "current_positions", risk_free_rate: Decimal = 0}`; response DTO `OptimizeResponse {weights: dict[str,str], expected_return: str, expected_volatility: str, constraints: list[ConstraintStatusDTO]}` (Decimals serialized as strings) with a `ConstraintStatusDTO {kind, satisfied, detail}`.
  - [x] Objective/method string → `Objective` enum / gate mapping helpers.
- [x] **Task 2 — Sector reader** (AC: #6)
  - [x] `market_data/repositories.py`: `sectors_for(session, stock_ids) -> dict[UUID, str]` — read `stocks.sector` for the ids (global table, no RLS), skipping NULL sectors. Small, mirrors existing readers.
- [x] **Task 3 — Route** (AC: #1, #3, #4, #5, #6)
  - [x] `api/routes_portfolios.py`: `POST /portfolios/{portfolio_id}/optimize` with `get_tenant_context`/`get_tenant_session`/`get_entitlement_service` deps.
  - [x] Order: `entitlements.check(ctx.tenant_id, "optimization")` (403) → `get_portfolio` guard (404) → method gate (advanced flag for BL/HRP; `validation_error` for non-`mean_variance`) → resolve `current_positions` via `list_positions` → `as_of = latest_price_date(session)` → `returns_matrix_as_of(...)` → `sectors_for(...)` → `MeanVarianceOptimizer().optimize(OptimizationRequest(objective, constraints.to_domain(), risk_free_rate, sector_of), returns)`.
  - [x] Success → `Envelope.ok(OptimizeResponse(...).model_dump(), meta={"disclaimer": DISCLAIMER})` + `_with_disclaimer(response)`; map `result.constraint_report.statuses` → `constraints[]`.
  - [x] Empty positions / no price date / too-thin matrix → a clear `validation_error` (not a 500).
- [x] **Task 4 — Exception handler** (AC: #4)
  - [x] `api/app.py`: `@app.exception_handler(InfeasibleConstraints)` → `_fail("infeasible", exc.binding.detail)`. Import `InfeasibleConstraints` from `quantvista.portfolio.constraints`.
- [x] **Task 5 — Tests** (AC: all)
  - [x] `tests/integration/test_api_optimize.py` (guard `pytest.importorskip("cvxpy")`): seed market + stocks (with `sector`) + ~1–2y daily prices + a Pro-tenant portfolio with positions. Cases: **200** (weights sum 1.0 as strings, `expected_return`/`expected_volatility` present, `constraints[]` populated, **`X-QuantVista-Disclaimer` header + `meta.disclaimer`**); **infeasible** (absurd `target_return`) → **422 `infeasible`** + binding constraint in message; **403** on a Free tenant (`optimization=false`); **404** cross-tenant / unknown id; **422** for `method=risk_parity` ("not yet available"); empty-positions → `validation_error`.
- [x] **Task 6 — Gates + reconcile** (AC: #7)
  - [x] Whole-tree ruff + `ruff format` + mypy + `lint-imports` clean; full suite green; coverage ≥ 80%. Reconcile QV-055 → done after merge; **watch CI to green** ([[feedback-full-tree-gates-and-watch-ci]]).

## Dev Notes

### This is a thin wiring story — reuse everything from QV-052/053/054
The optimizer, covariance, constraints model, returns reader, entitlement service, disclaimer helper, and envelope all exist. QV-055 is the **route + DTO boundary** that connects them. Do **not** re-implement any optimization logic, and do **not** modify `MeanVarianceOptimizer`/`Constraints`/`returns_matrix_as_of` — call them. [Source: `backend/src/quantvista/portfolio/optimizer.py`, `constraints.py`, `covariance.py`; `market_data/returns.py`]

### The constraints DTO is the one new primitive (deferred here on purpose)
QV-053/054 built `Constraints` as a domain value object and explicitly left the **JSON⇆`Constraints` (de)serialization** to QV-055. Build `OptimizeConstraints.to_domain()` mapping each field to the frozen `Constraints(...)`; per-field `[0,1]` bounds live at the Pydantic edge (like `schemas/portfolios.py`), and the cross-position/structural rules already live in `Constraints.__post_init__` + `check`/`feasibility`. Money is `Decimal`; on the wire weights/metrics serialize as **strings** (never float), matching the positions DTOs. [Source: `backend/src/quantvista/schemas/portfolios.py`; `backend/src/quantvista/portfolio/constraints.py`]

### Route pattern to mirror (near-copy)
`POST /portfolios` in `routes_portfolios.py` is the template for deps, the entitlement check, the 404-via-RLS pattern, and `Response`/`Envelope` usage. Add the optimize route in the **same file**. The disclaimer pattern is `routes_scores.py`/`routes_stocks.py`: `_with_disclaimer(response)` sets the header, `Envelope.ok(payload, meta={"disclaimer": DISCLAIMER})` sets the field — import both from `routes_stocks`. [Source: `backend/src/quantvista/api/routes_portfolios.py`; `backend/src/quantvista/api/routes_scores.py` lines 25, 69–70]

### Entitlement flags already seeded — don't add new ones
`optimization` (Free=false, Pro/Quant=true) gates the endpoint; `optimization_advanced` (Quant=true) gates BL/HRP. Use `EntitlementService.check(tenant_id, "optimization")` → raises `EntitlementExceeded` → the existing handler returns 403 `entitlement_exceeded`. No seed/migration change. [Source: `backend/src/quantvista/db/seeds/seed_reference.sql` lines 56–57, 77–78; `identity/entitlements.py`]

### Money/typing & PIT
`from __future__ import annotations`, modern typing, `Decimal` everywhere for money/weights. The returns matrix is PIT-bounded at `latest_price_date` (`date <= as_of`) — never "today's" look-ahead. `daily_prices`/`stocks` are global tables (no RLS); the portfolio/positions reads are tenant-RLS-scoped via the session. [Source: `[[market-data-provider-strategy]]`; project rules #1/#4]

### cvxpy is an optional extra — guard the test import
`routes_portfolios.py` will `import` the optimizer (→ cvxpy) at module load *only if* the optimize handler imports it at module top. To keep the base API import lean and the DB-only CI job green, **lazy-import** `MeanVarianceOptimizer`/`OptimizationRequest` **inside the optimize handler** (function-level import, FinBERT-style), and guard the integration test with `pytest.importorskip("cvxpy")`. This keeps `create_app()` importable without the `portfolio` extra while the optimize path pulls cvxpy on demand. [Source: `[[cvxpy-osqp-local-feasibility]]`; `backend/tests/test_portfolio_optimizer.py`]

### Scope boundary (what is NOT this story)
- Persisting `optimization_runs` / storing the result → QV-058 / later (optimize is a pure computation here).
- Risk-parity / Black-Litterman / HRP optimizers → QV-057+ (method returns "not yet available").
- `GET /portfolios/{id}/risk`, `POST /portfolios/{id}/rebalance` → QV-058 / QV-059.
- Frontend optimize UI → QV-056.
- A screen/universe candidate source beyond `current_positions` → later (only `current_positions` now).

### References
- [Source: `plans/sprints/sprint-06-portfolio-i.md#QV-055`] — story + AC (method/objective/constraints; infeasible+binding; disclaimer)
- [Source: `plans/04-api-contracts.md` §3.5] — optimize request/response contract, per-constraint status, `infeasible`+binding, tier-gated method
- [Source: `plans/04-api-contracts.md` §compliance header + `plans/07`] — disclaimer header + `meta.disclaimer`; project rule #7 (research not advice, D1)
- [Source: `backend/src/quantvista/portfolio/optimizer.py`] — `MeanVarianceOptimizer`, `OptimizationRequest/Result`, `Objective`, `InfeasibleConstraints`
- [Source: `backend/src/quantvista/market_data/returns.py`] — `returns_matrix_as_of`; `market_data/repositories.py` `latest_price_date`
- [Source: `backend/src/quantvista/api/routes_portfolios.py`, `routes_scores.py`, `routes_stocks.py`] — route + entitlement + disclaimer patterns
- [Source: `backend/src/quantvista/db/seeds/seed_reference.sql`] — `optimization` / `optimization_advanced` flags per plan

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- RED→GREEN: `test_optimize_schema` failed on the missing `_to_constraints` import; `test_api_optimize` on the missing route — both passed after implementation.
- **DAG correction (foundation-purity):** the story's Task 1 put `to_domain()` on the schema DTO, but `import-linter`'s `core and schemas import no domain context` contract forbids `schemas → portfolio`. Moved the DTO→`Constraints` mapping into an **api-layer** `_to_constraints` (in `routes_portfolios.py`); `schemas/optimize.py` stays pure wire DTOs. Contract stays KEPT.
- **Test-data date trap (not a code bug):** the first success run 422'd with "not enough observations". Cause: the shared dev DB's global `latest_price_date` was `2026-07-09`, so the route's `as_of` + 2y lookback excluded the fixture's 2024-dated bars. Fixed by seeding the 130 daily bars **ending at `date.today()`** so they're the newest series and fall inside the window. (Real prices are recent — a genuinely stale portfolio correctly returns infeasible.)
- Gates: ruff + `ruff format` + mypy (strict, **230 files**) + `lint-imports` (3/3, incl. schemas purity) clean; full suite **585 passed / 5 skipped**; new-code coverage **96%** (schemas 100%, routes_portfolios 94%).

### Completion Notes List

- **Thin wiring story — zero new domain logic.** The route calls the existing `MeanVarianceOptimizer` / `returns_matrix_as_of` / `Constraints` / entitlement / disclaimer / envelope. New code = the wire DTO (`schemas/optimize.py`), the api-layer mapping + route (`routes_portfolios.py`), a `sectors_for` reader (`market_data/repositories.py`), and one exception handler (`app.py`).
- **cvxpy stays lazy** — the optimizer is imported **inside** the optimize handler, so `create_app()` imports without the `portfolio` extra (verified). The integration test `pytest.importorskip("cvxpy")`-guards collection so the DB-only CI job stays green.
- **Gating order:** `optimization` flag (403 on Free) → BL/HRP also need `optimization_advanced` → portfolio 404 (RLS) → non-`mean_variance` method → `validation_error` (risk_parity=QV-057). `InfeasibleConstraints` → `infeasible` (422) + binding detail; `OptimizeError` (no positions / no prices / unavailable method) → `validation_error`.
- **Research-not-advice (D1):** reuses `DISCLAIMER` + `_with_disclaimer` — `X-QuantVista-Disclaimer` header **and** `meta.disclaimer` on success, asserted in the test.
- **Pure compute:** no `optimization_runs` persistence (deferred to QV-058), so no `Idempotency-Key` machinery. Money/weights are `Decimal`, serialized as strings on the wire.
- **Scope held:** no risk-parity/BL/HRP optimizers, no risk/rebalance endpoints, no FE, no candidate source beyond `current_positions`.

### File List

- Backend (impl): `src/quantvista/schemas/optimize.py` (new), `src/quantvista/api/routes_portfolios.py` (modified — optimize route + `_to_constraints` + `OptimizeError`), `src/quantvista/api/app.py` (modified — `InfeasibleConstraints`/`OptimizeError` handlers), `src/quantvista/market_data/repositories.py` (modified — `sectors_for`)
- Backend (tests): `tests/test_optimize_schema.py` (new), `tests/integration/test_api_optimize.py` (new)

## Change Log

- QV-055 story drafted (ready-for-dev): `POST /portfolios/{id}/optimize` wiring the QV-054 mean-variance optimizer — `OptimizeConstraints` DTO → QV-053 `Constraints`, PIT returns matrix from `current_positions`, entitlement (`optimization`) + method/tier gating, `InfeasibleConstraints` → `infeasible` (422) + binding constraint, and the research-not-advice disclaimer. Pure compute (no `optimization_runs` persistence); reuses optimizer/returns/disclaimer/entitlement — no new domain logic.
- QV-055 implemented (review): `schemas/optimize.py` (pure wire DTOs), `routes_portfolios.py` optimize route + `_to_constraints` (mapping in the api layer to keep schemas foundation-pure) + `OptimizeError`, `market_data.sectors_for`, and `app.py` `InfeasibleConstraints`→`infeasible`(422) / `OptimizeError`→`validation_error` handlers. cvxpy lazy-imported in the handler. 14 new tests (8 schema/mapping unit + 6 endpoint integration); 585 passed / 5 skipped; coverage 96%/100%; ruff/mypy(230)/lint-imports(3/3, schemas purity KEPT) clean.

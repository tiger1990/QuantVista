# Sprint 06 — Portfolio I (Build & Mean-Variance Optimize)

**Phase:** 3 · **Goal:** tenant-scoped portfolios and the first optimizer (Mean-Variance) with a real
constraints engine.
**Exit gate:** a user can build a portfolio and optimize allocation under constraints, end to end.

> See `../05-domain-and-quant.md` §1.3/§3, `../04` §3.5.

---

### QV-051 — Schema: portfolios + portfolio_positions (RLS) `[BE]` · `5pts` · Epic: EPIC-PORT · depends: QV-004
**Story:** As a user, I want to store portfolios, so I can analyze my holdings.
**Acceptance criteria:**
- `portfolios`/`portfolio_positions` tenant-scoped with RLS; cross-tenant denial test passes; `max_portfolios`
  entitlement enforced (US-06).
**Notes:** `03` §4.3.

### QV-052 — Portfolio CRUD API `[BE]` · `5pts` · Epic: EPIC-PORT · depends: QV-051, QV-007
**Story:** As a user, I want to create/manage portfolios and positions, so I curate them.
**Acceptance criteria:**
- `POST /portfolios` (Idempotency-Key) + positions CRUD; weights validated; entitlement-gated.
**Notes:** `04` §3.5.

### QV-053 — Constraints engine `[QUANT]` · `5pts` · Epic: EPIC-PORT · depends: —
**Story:** As a quant, I want a shared constraints model, so all optimizers honor the same rules.
**Acceptance criteria:**
- Constraints: max weight, sector caps, long-only, cardinality, target vol/return, turnover; infeasible
  problems report the **binding constraint** (no silent failure, US-03).
**Notes:** `05` §3.

### QV-054 — Mean-Variance optimizer (shrinkage covariance) `[QUANT]` · `8pts` · Epic: EPIC-PORT · depends: QV-053, QV-025
**Story:** As a quant, I want Markowitz optimization with stable covariance, so allocations are sensible.
**Acceptance criteria:**
- `MeanVarianceOptimizer` (`max_sharpe`/`min_vol`/target return); **Ledoit-Wolf shrinkage** covariance;
  weights sum to 1.0; constraints respected; expected return/vol returned.
**Notes:** Sample covariance instability is risk R7 (`09` §5).

### QV-055 — Optimize API `[BE]` · `3pts` · Epic: EPIC-PORT · depends: QV-054, QV-052
**Story:** As a user, I want to optimize a portfolio via API, so I get allocation weights.
**Acceptance criteria:**
- `POST /portfolios/{id}/optimize` with method/objective/constraints; success returns weights + metrics;
  infeasible → `error.code="infeasible"` + binding constraint; disclaimer present.
**Notes:** `04` §3.5; method gated by tier/phase.

### QV-056 — Frontend: Portfolio builder + optimization UI `[FE]` · `8pts` · Epic: EPIC-PORT · depends: QV-052, QV-055, QV-035
**Story:** As a user, I want to build and optimize portfolios visually, so allocation is intuitive.
**Acceptance criteria:**
- Add/remove holdings, set constraints, run optimize, view weights vs current (Recharts); clear infeasibility
  messaging; entitlement-aware (Free = 1 portfolio, no optimize).
**Notes:** `01` §4 / Pillar D.

**Sprint total:** ~34 pts.

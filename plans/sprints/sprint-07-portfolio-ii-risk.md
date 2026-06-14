# Sprint 07 — Portfolio II (Risk Parity, Risk Analytics, Rebalancing)

**Phase:** 3 · **Goal:** a second optimizer (Risk Parity), full risk analytics, and rebalancing suggestions
with drift alerts.
**Exit gate:** build → optimize → monitor risk → rebalance a portfolio end to end.

> See `../05-domain-and-quant.md` §1.3/§3, `../04` §3.5.

---

### QV-057 — Risk Parity optimizer `[QUANT]` · `5pts` · Epic: EPIC-PORT · depends: QV-053
**Story:** As a retail-oriented user, I want risk-balanced allocation, so no single name dominates risk.
**Acceptance criteria:**
- `RiskParityOptimizer` equalizes risk contribution under the shared constraints; selectable via `method`
  (Pro tier).
**Notes:** `05` §3 (phase 2).

### QV-058 — RiskEngine metrics `[QUANT]` · `8pts` · Epic: EPIC-PORT · depends: QV-025, QV-051
**Story:** As a user, I want portfolio risk metrics, so I understand exposure.
**Acceptance criteria:**
- Compute beta, annualized vol, max drawdown, Sharpe, Sortino, sector exposure, concentration (HHI); persist
  `risk_snapshots`; `GET /portfolios/{id}/risk` returns them.
**Notes:** `04` §3.5; `05` §1.3.

### QV-059 — Rebalancing + drift alerts `[BE]` `[QUANT]` · `5pts` · Epic: EPIC-PORT · depends: QV-058, QV-048
**Story:** As a user, I want suggested trades to reach target weights and drift alerts, so I stay on plan.
**Acceptance criteria:**
- `POST /portfolios/{id}/rebalance` returns suggested trades to targets within a drift threshold; portfolio
  drift alert rule type wired into `evaluate_alerts`.
**Notes:** `04` §3.5; `06` job catalog.

### QV-060 — Frontend: Risk dashboard + rebalancing UI `[FE]` · `8pts` · Epic: EPIC-PORT · depends: QV-058, QV-059, QV-056
**Story:** As a user, I want to monitor portfolio risk and act on rebalancing, so management is closed-loop.
**Acceptance criteria:**
- Risk dashboard (metrics, sector exposure, concentration, drawdown chart); rebalancing suggestions with
  apply-to-targets; method selector honors tier.
**Notes:** `01` Pillar D.

### QV-061 — Portfolio multi-tenancy isolation tests `[SEC]` · `3pts` · Epic: EPIC-PORT · depends: QV-051, QV-058
**Story:** As security, I want proof portfolios never leak across tenants, so isolation holds under portfolio
features.
**Acceptance criteria:**
- RLS + authz tests for portfolio/positions/risk endpoints across tenants; CI-gated.
**Notes:** `07` §3.

**Sprint total:** ~29 pts.

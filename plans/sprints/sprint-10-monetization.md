# Sprint 10 — Monetization (M-DATA Cutover + Stripe Billing)

**Phase:** 5 · **Goal:** complete the licensed-data cutover (the billing gate), wire Stripe billing +
entitlement sync, and make freemium gating live end to end.
**Exit gate:** licensed commercial data backs paid tiers; subscriptions drive entitlements; gating enforced.

> See `../03-data-architecture.md` §1 (M-DATA), `../04` §3.9 (billing), `../01` §4 (tiers).
> ⚠️ This sprint contains the **hard gate for charging money**.

---

### QV-072 — M-DATA: licensed India vendor adapter `[DATA]` · `8pts` · Epic: EPIC-DATA · depends: QV-010, QV-012
**Story:** As the platform, I want a commercially licensed data source behind the existing interface, so paid
tiers are served lawfully.
**Acceptance criteria:**
- New `IMarketDataProvider` adapter for the selected vendor (TrueData/Global Datafeeds per QV-010); coverage
  parity check vs dev source for Nifty 200; provenance `license_class` reflects commercial + display/
  redistribution rights.
- Zero changes to analytics code (proves the abstraction).
**Notes:** `03` §1; risk R1.

### QV-073 — Production data cutover + lineage verification `[DATA]` · `5pts` · Epic: EPIC-DATA · depends: QV-072
**Story:** As compliance, I want the paid pipeline running solely on licensed data with auditable lineage, so
we never serve a non-commercial source to paying users.
**Acceptance criteria:**
- Paid-tier reads sourced only from licensed provider; non-commercial dev source flagged and blocked from
  paid surfaces; data-lineage report shows source/license per served datum.
**Notes:** `03` §1 rule 2/3; Phase-3 "auditable data lineage."

### QV-074 — Stripe integration + checkout `[BE]` · `8pts` · Epic: EPIC-IDN · depends: QV-007
**Story:** As a user, I want to subscribe to a paid plan, so I unlock Pro/Quant features.
**Acceptance criteria:**
- `POST /billing/checkout-session` (Stripe Checkout); `GET /billing/portal`; **no card data touches our
  servers** (PCI: store only Stripe references).
- `subscriptions` table updated on success.
**Notes:** `04` §3.9; `07` §5.

### QV-075 — Stripe webhooks → entitlement sync `[BE]` · `5pts` · Epic: EPIC-IDN · depends: QV-074
**Story:** As the platform, I want subscription changes to update entitlements automatically, so access
matches billing.
**Acceptance criteria:**
- `POST /billing/webhook` verifies signature; on plan change updates `subscriptions` + invalidates the
  entitlement cache; idempotent (replay-safe).
**Notes:** `03` §8; `04` §3.9.

### QV-076 — Entitlement enforcement pass (all gated features) `[BE]` · `5pts` · Epic: EPIC-IDN · depends: QV-075
**Story:** As the platform, I want every tier-gated capability to read live entitlements, so limits are
consistent and not hard-coded.
**Acceptance criteria:**
- Screens, watchlists, portfolios, optimization methods, backtest range, alerts, news history, API access,
  exports all enforce `01` §4 via the Entitlement Service; over-limit → `entitlement_exceeded` + upgrade CTA.
**Notes:** `01` §4; US-06.

### QV-077 — Public API (Quant tier, read-only) + docs `[BE]` · `5pts` · Epic: EPIC-IDN · depends: QV-076
**Story:** As a Quant subscriber, I want programmatic read access, so I integrate QuantVista into my workflow.
**Acceptance criteria:**
- API-key auth (scoped, revocable, hashed), stricter rate limits, usage metering; read-only `/stocks`,
  `/scores`, `/rankings`, `/screener`; published OpenAPI + examples.
**Notes:** `04` §5; `07` §2.

### QV-078 — Frontend: pricing, upgrade flows, billing portal `[FE]` · `5pts` · Epic: EPIC-IDN · depends: QV-074, QV-076
**Story:** As a user, I want to compare plans and upgrade, so monetization is frictionless.
**Acceptance criteria:**
- Pricing page (tiers from `01` §4), upgrade CTAs at every gate, Stripe portal link, current-plan + usage
  display.
**Notes:** Final price points = O3 (config, not code).

**Sprint total:** ~46 pts · **🚧 Gate:** paid launch cannot proceed until QV-072/073 are complete.

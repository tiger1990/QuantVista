# Sprint 03 — Stock Intelligence (Scoring & UI)

**Phase:** 1 · **Goal:** the factor & scoring engine, persisted scores with decomposition, the intelligence
APIs, and the first user-facing UI.
**Exit gate (MVP-internal):** Nifty 200 scored daily, PIT-correct, visible in the UI with full score
explainability.

> See `../05-domain-and-quant.md` (engine), `../04-api-contracts.md` (endpoints), `../03` (scores schema).

---

### QV-028 — Factor framework + concrete factors `[QUANT]` · `8pts` · Epic: EPIC-INTEL · depends: QV-025, QV-021
**Story:** As a quant, I want pluggable factors reading PIT data, so the engine is extensible and bias-free.
**Acceptance criteria:**
- `Factor` ABC + concrete fundamental/momentum/quality/risk factors per `05` §2; each reads via PIT repos,
  returns `None` if unavailable.
- A factor cannot read "latest" data directly (enforced by review + a leakage test).
**Notes:** `05` §1.1.

### QV-029 — Normalizer + ScoreEngine + scores/factor_values schema `[QUANT]` · `8pts` · Epic: EPIC-INTEL · depends: QV-028, QV-024
**Story:** As a quant, I want cross-sectional normalization and weighted composite scoring, so each stock gets
explainable sub-scores + composite.
**Acceptance criteria:**
- Sector z-score → winsorize → 0–100 percentile; category blend via versioned `ScoreWeights` (defaults `05`
  §2).
- Persist `scores` + `factor_values`; **decomposition sums to composite**; `weights_version`/`model_version`
  recorded.
- Missing-factor policy: exclude + re-normalize category; coverage flag stored.
**Notes:** `05` §1.2.

### QV-030 — `compute_factors` + `compute_scores` jobs `[QUANT]` · `5pts` · Epic: EPIC-INTEL · depends: QV-029
**Story:** As the platform, I want daily factor/score computation triggered by data events, so scores stay
fresh.
**Acceptance criteria:**
- `compute_factors` on indicators+fundamentals → `FactorsComputed`; `compute_scores` → `ScoresComputed`.
- Idempotent per `(universe, date)`; meets freshness SLO (scores ready before 09:15 IST next day).
**Notes:** `06` §3.

### QV-031 — Caching + invalidation on `ScoresComputed` `[BE]` · `3pts` · Epic: EPIC-INTEL · depends: QV-030
**Story:** As a user, I want fast score reads, so the dashboard is snappy.
**Acceptance criteria:**
- Redis caches current scores/rankings/stock-detail; invalidated on `ScoresComputed`; TTL backstop.
**Notes:** `03` §8.

### QV-032 — API: /stocks, /stocks/{symbol} `[BE]` · `5pts` · Epic: EPIC-INTEL · depends: QV-031, QV-007
**Story:** As a user/client, I want to list and inspect stocks, so I can browse the universe.
**Acceptance criteria:**
- `GET /stocks` with filter/sort/cursor pagination; `GET /stocks/{symbol}` returns master + latest snapshot.
- Standard envelope; disclaimer field on score-bearing responses.
**Notes:** `04` §3.2.

### QV-033 — API: /scores/{symbol} + /decomposition + /rankings `[BE]` · `5pts` · Epic: EPIC-INTEL · depends: QV-031, QV-007
**Story:** As an analyst, I want scores, their decomposition, and rankings, so I can trust and rank stocks.
**Acceptance criteria:**
- `/scores/{symbol}?as_of=`; `/scores/{symbol}/decomposition` proves parts sum to composite with PIT input
  dates (US-02 AC); `/rankings` respects entitlement (Free → top-50).
**Notes:** `04` §3.3.

### QV-034 — Frontend: app shell, auth flows, design system base `[FE]` · `8pts` · Epic: EPIC-INTEL · depends: QV-006
**Story:** As a user, I want to sign in and navigate, so I can use the product.
**Acceptance criteria:**
- Next.js shell (nav, auth, protected routes), MUI theme + intentional design tokens, TanStack Query client,
  generated typed API client from OpenAPI.
**Notes:** Web design-quality rules apply (no template look).

### QV-035 — Frontend: Dashboard + Stocks list `[FE]` · `5pts` · Epic: EPIC-INTEL · depends: QV-034, QV-032, QV-033
**Story:** As a user, I want a market overview and ranked stocks, so I see value immediately.
**Acceptance criteria:**
- Dashboard: market overview, top-ranked stocks, sector heatmap; Stocks list with filter/sort, URL-shareable
  state; visible non-advice disclaimer.
**Notes:** `01` Pillar A/B.

### QV-036 — Frontend: Stock detail with score decomposition `[FE]` · `5pts` · Epic: EPIC-INTEL · depends: QV-034, QV-033
**Story:** As an analyst, I want to see why a stock scores as it does, so I trust the signal.
**Acceptance criteria:**
- Detail page shows price, key fundamentals, sub-scores, and a **decomposition view** (factor contributions
  with PIT as-of dates) summing to the composite.
**Notes:** US-02; the explainability differentiator.

### QV-037 — Leakage/PIT regression test for scoring `[QUANT]` · `3pts` · Epic: EPIC-INTEL · depends: QV-030
**Story:** As QA, I want a guard against look-ahead bias in scoring, so credibility is protected permanently.
**Acceptance criteria:**
- Synthetic fixture that only passes if scoring uses no post-`as_of` data; runs in CI as non-skippable.
**Notes:** Companion to backtest bias tests (`05` §4).

**Sprint total:** ~63 pts (consider splitting QV-034) · **Milestone:** 🎯 **MVP-internal demo.**

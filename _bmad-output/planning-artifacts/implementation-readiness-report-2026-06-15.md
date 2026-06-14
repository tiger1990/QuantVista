# Implementation Readiness Assessment Report

**Date:** 2026-06-15
**Project:** FinanceStockManager (QuantVista)
**Assessor:** BMAD Implementation Readiness (bmad-check-implementation-readiness)

> **Assessment basis:** PRD (`planning-artifacts/prd.md`, canonical of `plans/01-prd.md`), Architecture
> (`planning-artifacts/architecture.md`, consolidating `plans/02–08`), Epics (`planning-artifacts/epics.md`,
> bridged from `plans/sprints/`, 10 epics / 91 stories). UX: none (deliberately deferred — WDS planned
> before Sprint 03). Authoritative detail lives in `plans/`.

---

## Document Discovery

| Document | Status | Source |
|---|---|---|
| PRD | ✅ Found | `planning-artifacts/prd.md` |
| Architecture | ✅ Found | `planning-artifacts/architecture.md` |
| Epics & Stories | ✅ Found | `planning-artifacts/epics.md` (10 epics, 91 stories) |
| UX | ⚠️ Not found | Deferred by decision (UI not needed until Sprint 03) |

No duplicate formats. No unresolved conflicts.

---

## PRD Analysis

### Functional Requirements (derived from pillars + user stories)

- FR1: Daily per-stock scores (Fundamental, Momentum, Quality, Sentiment, Risk) + Composite signal.
- FR2: Full factor decomposition / explainability ("why this score"), PIT inputs.
- FR3: Historical score trends + sector/universe percentile ranks.
- FR4: Screener — filter/sort across factors, fundamentals, ownership, technicals.
- FR5: Side-by-side comparison of up to N stocks.
- FR6: Saved screens (entitlement-limited).
- FR7: Per-stock news feed with FinBERT sentiment + event-impact score.
- FR8: Sentiment trend over time; sentiment as a scoring input.
- FR9: Build portfolios manually or from a ranked universe.
- FR10: Optimize allocation (MVO → Risk Parity → Black-Litterman / HRP across phases).
- FR11: Risk analytics (beta, vol, drawdown, Sharpe/Sortino, exposure, concentration).
- FR12: Rebalancing suggestions + portfolio drift alerts.
- FR13: Backtesting with survivorship- and look-ahead-bias controls.
- FR14: Performance & risk metrics + Nifty 200 TRI benchmark.
- FR15: Alerts — threshold (score/PE/RSI/drift), news-event, scheduled digests; in-app + email.
- FR16: Freemium tiers + centralized Entitlement Service; Stripe billing.
- FR17: AuthN + multi-tenant isolation (register/login, tenant context).
- FR18: Public read-only REST API (Quant tier, rate-limited).
- FR19: Data export (CSV; bulk on Quant).
- FR20: Market-data ingestion (prices, fundamentals, corp actions, shareholding, macro, index constituents) via provider abstraction.

**Total FRs: 20**

### Non-Functional Requirements

- NFR1: API latency p95 <300 ms cached; <1 s screener over full universe.
- NFR2: Availability 99.5% → 99.9% (multi-AZ at scale).
- NFR3: Data freshness — EOD scores before next IST open; news ~15 min.
- NFR4: Pipeline correctness — idempotent, replayable, PIT-correct.
- NFR5: Security — RLS tenant isolation; OWASP ASVS L2.
- NFR6: Privacy — India DPDP Act 2023.
- NFR7: Scalability — 10k tenants / 100k MAU on modular monolith.
- NFR8: Observability — RED/USE metrics, traces, structured logs, alerts.

**Total NFRs: 8**

### PRD completeness

Strong. Personas, JTBD, pillars, entitlement matrix, representative stories with ACs, NFRs, explicit
non-goals, and success metrics all present. Pricing (O3) and production data vendor (O2) intentionally
deferred behind interfaces — not blocking.

---

## Epic Coverage Validation

### FR coverage matrix

| FR | Coverage (epic · stories) | Status |
|----|---------------------------|--------|
| FR1 | E4 · QV-028/029/030 | ✅ |
| FR2 | E4 · QV-029/033/036 | ✅ |
| FR3 | E4 · QV-029/033 (rankings/percentiles) | ✅ |
| FR4 | E4 · QV-038/040 | ✅ |
| FR5 | E4 · QV-040 (comparison view) | ✅ |
| FR6 | E4 · QV-039 | ✅ |
| FR7 | E5 · QV-041/042/043/044/045 | ✅ |
| FR8 | E4/E5 · QV-046 (factor); QV-043 (feed) | ◑ trend-over-time UI not explicit |
| FR9 | E7 · QV-051/052/056 | ✅ |
| FR10 | E7 · QV-054 (MVO), QV-057 (Risk Parity) | ◑ **Black-Litterman / HRP not storied** (phased) |
| FR11 | E7 · QV-058 | ✅ |
| FR12 | E7 · QV-059/060 | ✅ |
| FR13 | E8 · QV-062/063/064/065/066 | ✅ |
| FR14 | E8 · QV-068 | ✅ |
| FR15 | E6 · QV-047/048/049/050 | ◑ **scheduled digests** not explicit |
| FR16 | E2 · QV-007/074/075/076 | ✅ |
| FR17 | E2 · QV-004/006/007 | ✅ |
| FR18 | E2 · QV-077 | ✅ |
| FR19 | — | ❌ **No story implements CSV/bulk export** (entitlements reference it) |
| FR20 | E3 · QV-012–026/072/073 | ✅ |

### Coverage statistics

- Total PRD FRs: **20**
- Fully covered: **16**
- Partial / phased: **3** (FR8 trend UI, FR10 BL/HRP, FR15 digests)
- Missing: **1** (FR19 data export)
- **Coverage ≈ 90% (95% if phased items counted as intentional deferrals)**

### NFR coverage

All 8 NFRs have implementing or enforcing stories (caching QV-031; infra/HA QV-008/082/083/084; freshness
QV-016/020; correctness QV-015/018/027/037/066; security QV-004/061/079; DPDP QV-080; scalability +
load/soak QV-085; observability QV-009/020/082). Strong. Note: no dedicated screener-latency (NFR1)
performance-test story beyond the general load/soak (QV-085, Sprint 11) — consider an earlier perf check.

---

## UX Alignment Assessment

### UX document status: **Not found**

### Findings

- UI is unambiguously a **primary product surface**: multiple `[FE]` stories (QV-034/035/036/040/050/056/
  060/071/078), four personas, and pillars built around dashboards, screener, decomposition views, and charts.
- ⚠️ **WARNING:** No UX/design artifacts exist. Per BMAD this is a warning when UI is implied — it is.
- **Mitigation (accepted):** UX is deliberately deferred and scheduled via the WDS pipeline **before
  Sprint 03** (first UI-bearing sprint). Sprint 00–02 are backend/data/infra, so this does not block near-term
  work — but it **must** be resolved before QV-034 (frontend app shell) begins.

---

## Epic Quality Review (against create-epics-and-stories standards)

> Direct, per step-05's mandate. The backlog is exceptionally thorough; the findings below are mostly
> **structural deviations from BMAD's epic philosophy**, not defects in the work itself.

### 🔴 Critical
- None that block starting implementation. The dependency graph is internally consistent **when executed in
  sprint order** (its intended sequencing).

### 🟠 Major
1. **Technical/infrastructure epics.** BMAD wants epics to deliver user value, not technical milestones.
   Epic 1 (Platform/CI/IaC/Observability), Epic 3 (Market-Data Ingestion), and Epic 10 (Compliance) are
   workstream/technical epics with no direct end-user feature. **Assessment:** deliberate and defensible for
   a data/quant platform where the PIT-correct data backbone *is* a prerequisite capability — but it is a
   real deviation from BMAD's user-value-epic rubric. No change required if the team owns this choice.
2. **Epic independence / forward dependencies.** Epics here are *workstreams spanning multiple sprints*, so
   BMAD's "Epic N must not depend on Epic N+1" rule is violated in places:
   - QV-046 (Epic 4 · Sentiment factor) depends on QV-044 (Epic 5 · FinBERT) → Epic 4 → Epic 5 forward dep.
   - Epic 1 hardening stories (QV-079, QV-020) depend on QV-076 (Epic 2) and QV-015 (Epic 3).
   **Assessment:** the dependencies are valid by **sprint sequence** (QV-046 and QV-044 are both Sprint 05),
   but the *epic numbering* is not an independent-shippable-increment model. Acceptable if you track by
   sprint, not by epic independence.
3. **Coverage gaps (from step 3):** FR19 (data export) has **no implementing story** — add one;
   FR10 BL/HRP optimizers are not storied (PRD says "across phases", so likely post-v1 — confirm intent).

### 🟡 Minor
1. **Acceptance criteria are bullet-form**, not Given/When/Then. Testable and clear, but not BDD-structured.
2. **Scheduled digests** (part of FR15) and **sentiment trend-over-time UI** (FR8) not explicitly storied.
3. **UX artifacts absent** (see UX section).

### Positives
- ✅ Greenfield project-setup story present and first: QV-001 (monorepo + module skeleton).
- ✅ Stories sized in Fibonacci; 13-pt = split rule documented.
- ✅ Database tables created when needed per workstream (not all upfront beyond the already-built `db/` layer).
- ✅ Strong correctness discipline baked into stories (RLS denial tests, bias-regression, PIT leakage tests).
- ✅ Every story carries a canonical QV-### ID with full ACs traceable to `plans/sprints/`.

---

## Summary and Recommendations

### Overall Readiness Status: **READY — with minor follow-ups**

Planning is well above typical readiness. The "violations" are predominantly BMAD-philosophy mismatches
(sprint/workstream epics vs user-value epics; epic-number independence) that are **deliberate and coherent**
for a data-platform build. Nothing blocks starting **Sprint 00**.

### Issues to address (not blocking Sprint 00)

1. **Add a data-export story (FR19).** CSV (Pro) + bulk (Quant) are entitlement-listed but unstoried. Place
   in Epic 4/Epic 2 around the API work (e.g., a new QV-### in Sprint 04/10).
2. **Confirm BL/HRP intent (FR10).** Either add stories or explicitly mark Black-Litterman/HRP as post-v1.
3. **Resolve UX before Sprint 03.** Run the WDS pipeline (Project Brief → Trigger Map → Scenarios → Specs)
   so QV-034 (app shell) has a design to build against. Hard dependency for the UI track.
4. **Minor:** add scheduled-digest + sentiment-trend stories; consider an early screener-latency perf check
   (NFR1) rather than waiting for QV-085.

### Recommended next steps

1. Proceed to the build loop for Sprint 00 — `[CS] create-story` for QV-001 (no blockers).
2. Backfill the FR19 export story and confirm FR10 scope when convenient (before Sprint 04/06 respectively).
3. Kick off WDS UX before Sprint 03.

### Final note

This assessment identified **1 missing requirement, 3 partial/phased gaps, and 3 structural epic
deviations** across coverage, UX, and epic-quality categories. The structural deviations are intentional;
the genuine action item is the FR19 export story. You may proceed to implementation as-is and address these
in parallel.

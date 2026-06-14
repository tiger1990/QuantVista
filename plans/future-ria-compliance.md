# Future Plan — RIA-Grade Advisory Compliance (SEBI / SEC)

> **Status:** Deferred (not part of v1). Triggered only if QuantVista intends to provide **personalized
> investment advice for a fee**. This is a separate program, not a feature. Keep it out of v1 to preserve the
> research-tool posture (D1, `07`).

---

## 1. When this unlocks

Cross from "research tool" to "advisory" the moment we do **any** of:
- Tell an identifiable user what *they specifically* should buy/sell/hold;
- Tailor recommendations to a user's financial situation, goals, or risk profile (suitability);
- Charge a fee for that personalized advice or for managing assets.

Until then, v1 must avoid all of the above (enforced in `07` §1).

## 2. Regulatory landscape (to validate with counsel)

- **India — SEBI (Investment Advisers) Regulations, 2013** (as amended): registration as an Investment
  Adviser (IA), qualification & certification (NISM), net-worth requirements, fee caps/modes, mandatory
  **risk profiling & suitability**, segregation of advice vs distribution, compliance audit, record-keeping.
- **US — SEC/State RIA:** Investment Advisers Act of 1940; Form ADV; fiduciary duty; books-and-records rule;
  custody rule (if applicable); marketing rule.
- **This plan does not constitute legal advice** — engage securities counsel before executing.

## 3. Capabilities to build

1. **KYC & onboarding:** identity verification, risk-profiling questionnaire, suitability assessment, consent
   & agreement capture.
2. **Suitability engine:** map client profile (risk tolerance, horizon, constraints, existing holdings) to
   permitted recommendations; block unsuitable advice.
3. **Advice records (immutable):** every personalized recommendation stored with rationale, inputs,
   suitability basis, adviser identity, timestamp, and what the client was shown — tamper-evident,
   long-retention.
4. **Adviser workflow & roles:** registered-adviser accounts, supervision/approval, audit trails.
5. **Fee management & disclosures:** fee agreements, conflict-of-interest disclosures, periodic statements.
6. **Compliance reporting:** regulator-ready reports, periodic audits, complaint handling/redressal.
7. **Enhanced data governance:** stricter retention, access controls, e-sign, archival per regulation.

## 4. Architectural impact

- New **Advisory** bounded context (suitability, advice records, adviser supervision) — slots in via the
  same module/interface pattern (`02`).
- Strengthen `audit_log` into a dedicated **immutable advice-records store** (WORM/object-lock).
- Identity module gains KYC, risk-profile entities, adviser roles.
- The research scoring/optimization engines are **reused** — advisory adds the *personalization +
  recordkeeping + supervision* layer on top.

## 5. Sequencing

Counsel engagement → gap assessment → registration prerequisites (qualification, net worth) → build KYC/
suitability/records → compliance review → controlled rollout. Long lead time; budget accordingly.

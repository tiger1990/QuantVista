# Sprint 11 — Launch Hardening (Security, DPDP, SLOs) → PAID LAUNCH

**Phase:** 5 · **Goal:** harden security to ASVS L2, implement DPDP data-subject flows, complete audit
logging, finalize observability/SLOs, prove backup/restore, load test, and finalize compliance content.
**Exit gate:** 🎯 **PAID LAUNCH** — licensed data + billing + compliance + SLOs all green.

> See `../07-security-and-compliance.md`, `../08-infra-devops-observability.md`.

---

### QV-079 — Security hardening pass (OWASP ASVS L2) `[SEC]` · `8pts` · Epic: EPIC-PLAT · depends: QV-076
**Story:** As security, I want a baseline-compliant app, so launch risk is acceptable.
**Acceptance criteria:**
- CSP (nonce), security headers, CSRF, rate limiting (auth + public API), SSRF allow-list, input validation
  audit; `security-reviewer` sign-off on auth/billing/data paths; SAST/SCA/secret/container scans clean.
**Notes:** `07` §4/§7.

### QV-080 — DPDP data-subject flows (consent, access, erasure) `[BE]` `[SEC]` · `8pts` · Epic: EPIC-COMP · depends: QV-076
**Story:** As a user, I want my privacy rights honored, so the platform is DPDP-compliant.
**Acceptance criteria:**
- Consent capture at signup + privacy notice; data-access export; **account/tenant deletion purges PII +
  tenant data** while preserving lawful anonymized aggregates; retention policy enforced.
**Notes:** `07` §5.

### QV-081 — Audit logging complete `[SEC]` · `5pts` · Epic: EPIC-COMP · depends: QV-079
**Story:** As compliance, I want security/money actions logged immutably, so we have accountability.
**Acceptance criteria:**
- `audit_log` covers auth, role/entitlement, portfolio/alert CRUD, billing, exports, admin; append-only;
  shipped to centralized logging; retention set.
**Notes:** `07` §6.

### QV-082 — Observability, SLOs & alerting finalized `[PLAT]` · `5pts` · Epic: EPIC-PLAT · depends: QV-009
**Story:** As an operator, I want production SLOs and actionable alerts, so we run reliably.
**Acceptance criteria:**
- Dashboards (API RED, worker, freshness, infra USE, business); SLO alerts (availability, p95 latency,
  freshness, job success, data-quality) route to on-call with runbooks; synthetic checks on key journeys.
**Notes:** `08` §6/§7.

### QV-083 — Backup, PITR & restore drill `[PLAT]` · `5pts` · Epic: EPIC-PLAT · depends: QV-008
**Story:** As an operator, I want proven recovery, so data loss is survivable.
**Acceptance criteria:**
- Automated Postgres snapshots + PITR; object-store versioning; **a documented restore drill executed
  successfully**; RPO/RTO recorded.
**Notes:** `08` §8.

### QV-084 — Production CD pipeline + staging gates `[PLAT]` · `5pts` · Epic: EPIC-PLAT · depends: QV-003, QV-008
**Story:** As the team, I want safe automated deploys, so releases are repeatable and reversible.
**Acceptance criteria:**
- main→image (Trivy-scanned)→migration check→staging deploy→integration+E2E (Playwright)+smoke→manual
  approval→rolling prod deploy→post-deploy smoke + freshness check; documented rollback.
**Notes:** `08` §5.

### QV-085 — Load & soak test `[PLAT]` · `3pts` · Epic: EPIC-PLAT · depends: QV-082
**Story:** As an operator, I want to know our capacity, so launch traffic doesn't break us.
**Acceptance criteria:**
- Load test API + pipeline at target scale (`01` NFRs); identify/right-size bottlenecks; results documented;
  autoscaling verified.
**Notes:** `08`; risk R8.

### QV-086 — Launch compliance content finalized `[PROD]` · `2pts` · Epic: EPIC-COMP · depends: QV-070, QV-080
**Story:** As compliance, I want T&C, privacy policy, and methodology/disclaimer live, so public launch is
lawful.
**Acceptance criteria:**
- T&C, privacy policy (DPDP), Methodology & Disclaimer published and linked; non-advice language audited
  across all research surfaces.
**Notes:** `07` §1; launch-blocking.

**Sprint total:** ~41 pts · **Milestone:** 🎯 **PUBLIC PAID LAUNCH.**

# 07 — Security & Compliance

> AuthN/Z, tenant isolation, secrets, **non-advice regulatory posture (D1)**, India DPDP alignment,
> audit logging. Baseline target: OWASP ASVS Level 2.

---

## 1. Regulatory posture (D1) — research tool, not advice

This shapes product copy, data flows, and records. The goal: deliver high-value analytics while staying
clearly outside "investment advice" that triggers SEBI Investment Adviser regulation (or SEC RIA in the US).

**Rules enforced product-wide:**
1. **No personalization of recommendations.** Scores/rankings/optimizations are computed from public data
   and user-chosen parameters — never from a user's financial situation, risk profile, or goals. (Suitability
   = advice; that's the future-plan line.)
2. **Language discipline.** "Research signal", "factor score", "screened candidates" — **not** "we recommend
   you buy", "suitable for you". A terminology guide is part of the design system.
3. **Disclaimers everywhere research output appears:** UI banners + the `disclaimer` field + the
   `X-QuantVista-Disclaimer` header (`04`). T&C and a "Methodology & Disclaimer" page are launch-blocking.
4. **No execution, no custody, no brokerage** in v1 (non-goals, `01`).
5. **Transparent methodology.** Published scoring methodology + backtest assumptions; reduces "black-box
   advice" perception and builds trust.
6. **Records.** Retain what outputs were shown and how derived (`model_version`, `weights_version`,
   `as_of`) — useful for trust now and a head start for the RIA path later.

> The regulated-advisory evolution (KYC, suitability, advice records, adviser registration) is intentionally
> **out of scope** and fully specified in `future-ria-compliance.md`. Do not let advisory features leak into v1.

---

## 2. Authentication

- **Users:** email+password (Argon2id hashing), email verification, optional **TOTP MFA**. Social OAuth
  (Google) for friction-free signup. Org SSO (SAML/OIDC) deferred to enterprise.
- **Tokens:** short-lived access JWT (~15 min) + rotating refresh token. Web: refresh in httpOnly, Secure,
  SameSite cookie. Programmatic (Quant): scoped, revocable **API keys** (hashed at rest), per-key rate limits.
- **Session security:** refresh-token rotation with reuse detection (revoke family on reuse); device/session
  list; logout-all.

---

## 3. Authorization & tenant isolation (defense in depth)

1. **Database (primary):** PostgreSQL **Row-Level Security** on every tenant-scoped table; request
   transaction sets `app.tenant_id`; policies bind every row to the tenant. A logic bug cannot leak across
   tenants. (D6, `02`/`03`.)
2. **Application:** RBAC within a tenant — roles `owner | admin | member` via `memberships`. Endpoint
   guards check role + entitlement.
3. **Entitlements:** capability/limit checks (plan-driven) at the API boundary → `entitlement_exceeded`.
4. **Reference data:** global tables are read-only to tenants; only privileged job role writes them.

**Tests:** RLS cross-tenant denial tests + authz tests are CI-gated; a failing isolation test blocks merge.

---

## 4. Application security (OWASP)

- **Input validation:** Pydantic at every boundary; reject unknown fields; strict types for financial values.
- **Injection:** SQLAlchemy parameterized queries only; no string-built SQL. JSONB criteria validated against
  an allow-list of fields/operators (screener/alert specs).
- **XSS:** React auto-escaping; sanitize any rendered news/HTML; strict CSP with nonces (per web rules).
- **CSRF:** cookie-based web auth protected with SameSite + CSRF tokens on state-changing requests.
- **Rate limiting & abuse:** per-IP and per-tenant limits; stricter on auth + public API; bot/abuse controls
  on signup.
- **SSRF:** outbound data-vendor/news calls go through an allow-listed HTTP client; no user-controlled URLs
  fetched server-side.
- **Headers:** HSTS, X-Content-Type-Options, X-Frame-Options/ frame-ancestors, Referrer-Policy,
  Permissions-Policy (per web security rules).
- **Dependencies:** SCA scanning (e.g., `pip-audit`, Dependabot); container image scanning (Trivy) in CI.
- **Secrets:** never in repo; cloud secret manager (AWS Secrets Manager/SSM); rotation policy; startup
  validates required secrets present (fail fast).

---

## 5. Data protection & privacy (India DPDP Act 2023)

- **Scope:** user PII (email, name, billing identifiers). Market/reference data is non-personal.
- **Lawful basis & consent:** explicit consent at signup; clear privacy notice; purpose limitation.
- **Data subject rights:** access, correction, **erasure** (right to be forgotten) — implemented as tenant/
  user deletion that purges PII and tenant data while preserving anonymized/aggregate analytics where lawful.
- **Data minimization & retention:** store only needed PII; documented retention; delete on request/closure.
- **Security safeguards:** encryption in transit (TLS 1.2+) and at rest (DB/object store); least-privilege IAM.
- **Processors:** Stripe (billing), email provider, cloud, data vendors — under DPAs; data residency in the
  India region where feasible.
- **Breach process:** detection → assessment → notification per DPDP timelines; runbook in `08`.
- **PCI:** **no card data touches our servers** — Stripe Checkout/Elements; we store only Stripe references.

---

## 6. Audit logging

- `audit_log` (`03`) records security- and money-relevant actions: auth events, role/entitlement changes,
  portfolio/alert CRUD, billing changes, data exports, admin actions — with actor, tenant, before/after, IP.
- Immutable/append-only; shipped to centralized logging (`08`); retained per policy.
- Distinct from `jobs_runs` (operational) and from research-output records (§1.6).

---

## 7. Secure SDLC

- Branch protection, mandatory review (`code-reviewer` / `security-reviewer` for sensitive paths), no direct
  pushes to `main`.
- CI gates: SAST, SCA, secret scanning, container scan, RLS/authz tests must pass before merge.
- Threat modeling at design time for new modules handling auth, billing, or external input.
- Least-privilege service accounts; separate prod credentials; break-glass procedure documented.

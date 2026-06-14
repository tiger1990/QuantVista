# Sprint 00 — Foundations & Scaffolding

**Phase:** 0 · **Goal:** a request can authenticate, set tenant context, and hit a health endpoint in
staging; module skeleton + CI + IaC baseline in place; M-DATA procurement and compliance content started.
**Exit gate:** auth + tenant context working in staging; CI green; import-linter enforces module DAG.

> See `../02-architecture.md` (modules/seams), `../03-data-architecture.md` (RLS), `../07-...` (auth),
> `../08-...` (infra/CI). DoD per `../09-roadmap-and-delivery.md` §4.

---

### QV-001 — Monorepo & module skeleton with dependency linting `[PLAT]` · `5pts` · Epic: EPIC-PLAT · depends: —
**Story:** As an engineer, I want a structured repo with enforced module boundaries, so workstreams build in
parallel without creating cycles.
**Acceptance criteria:**
- Backend package layout mirrors the bounded contexts in `02` (identity, market_data, news, analytics,
  portfolio, alerts, platform/core) + `api`, `jobs`, `schemas`, `db`.
- `import-linter` (or equivalent) configured to enforce the dependency DAG; a forbidden import fails CI.
- Frontend (Next.js/TS) app scaffolded with feature-folder structure.
**Notes:** Modules expose interfaces only; no cross-module table access (`02` §4).

### QV-002 — Local dev environment (docker-compose) `[PLAT]` · `3pts` · Epic: EPIC-PLAT · depends: QV-001
**Story:** As an engineer, I want one-command local infra, so I can run the full stack locally.
**Acceptance criteria:**
- `docker-compose up` brings up postgres, redis, minio, api, worker, beat, web.
- Seed script runs; healthcheck endpoints green; README documents setup.
**Notes:** Same image runs api/worker/beat by command (`08` §2).

### QV-003 — Base CI pipeline `[PLAT]` · `5pts` · Epic: EPIC-PLAT · depends: QV-001
**Story:** As a team, I want automated checks on every PR, so quality is enforced from day one.
**Acceptance criteria:**
- GitHub Actions: Ruff lint, mypy, pytest (unit), coverage gate ≥80%, frontend lint+typecheck+unit, build.
- SAST + secret scan + `pip-audit` (SCA) run on PR; failing any blocks merge.
- Branch protection on `main`: required reviews + green checks.
**Notes:** Full CD added in Sprint 10–11; this is the PR gate (`08` §5).

### QV-004 — PostgreSQL + Alembic + RLS scaffolding `[BE]` · `8pts` · Epic: EPIC-IDN · depends: QV-002
**Story:** As an engineer, I want migrations and tenant isolation primitives, so tenant data is isolated by
construction.
**Acceptance criteria:**
- Alembic configured; expand/contract migration convention documented (`03` §9).
- Session sets `app.tenant_id` per request transaction; helper for privileged (reference-data) role.
- A demo tenant-scoped table has an RLS policy; **cross-tenant access denial test passes in CI**.
**Notes:** RLS is the primary isolation layer (`03` §2 / `07` §3).

### QV-005 — Reference seed data (markets, plans, entitlements, Nifty 200 constituents) `[DATA]` · `3pts` · Epic: EPIC-IDN · depends: QV-004
**Story:** As the platform, I want seed reference data, so plans/markets/universe exist before features.
**Acceptance criteria:**
- `markets` (NSE), `plans` (free/pro/quant), `entitlements` per plan, and point-in-time `index_constituents`
  for NIFTY200 seeded idempotently.
- Re-running the seed is a no-op (idempotent).
**Notes:** Constituents must be PIT-capable from the start (survivorship, `03` §5).

### QV-006 — AuthN: register / login / JWT + refresh rotation `[BE]` · `8pts` · Epic: EPIC-IDN · depends: QV-004
**Story:** As a user, I want to sign up and log in securely, so I can access the platform.
**Acceptance criteria:**
- Register creates a tenant + owner user (Free plan); Argon2id hashing; email verification stub.
- Login issues short-lived access JWT + rotating refresh (httpOnly cookie for web); refresh-reuse detection.
- `GET /me` returns user + active tenant + entitlements summary.
**Notes:** `07` §2; tokens/sessions per `04` §1.

### QV-007 — Tenant-context middleware + Entitlement Service (stub) `[BE]` · `5pts` · Epic: EPIC-IDN · depends: QV-006
**Story:** As the API, I want resolved tenant context and entitlement checks, so gating is centralized.
**Acceptance criteria:**
- Middleware resolves tenant from principal and binds it to the DB session (sets `app.tenant_id`).
- `IEntitlementService.get(tenant)` returns plan limits/flags (reads seed); `entitlement_exceeded` error
  shape available (`04` §1).
**Notes:** Real Stripe sync arrives Sprint 10; interface is final now.

### QV-008 — IaC bootstrap (AWS staging) `[PLAT]` · `8pts` · Epic: EPIC-PLAT · depends: —
**Story:** As the team, I want reproducible staging infra, so deploys aren't click-ops.
**Acceptance criteria:**
- Terraform provisions VPC, EKS, RDS Postgres, ElastiCache Redis, S3, IAM, Secrets Manager in `ap-south-1`.
- Remote state + locking; per-env workspace; staging reachable.
**Notes:** AWS per **D8**; IaC keeps it portable (`08` §4).

### QV-009 — Observability baseline `[PLAT]` · `5pts` · Epic: EPIC-PLAT · depends: QV-008
**Story:** As an operator, I want metrics/logs/traces from day one, so we never fly blind.
**Acceptance criteria:**
- OpenTelemetry tracing in api/worker; structured JSON logs with request/trace IDs; Prometheus metrics
  endpoint; Grafana + Sentry wired in staging.
**Notes:** `08` §6.

### QV-010 — [SPIKE] M-DATA: India data-vendor evaluation `[PROD]` · `5pts` · Epic: EPIC-COMP · depends: —
**Story:** As product/legal, I want a vendor decision matrix, so commercial licensing isn't a launch blocker.
**Acceptance criteria:**
- Evaluate TrueData & Global Datafeeds (primary) vs NSE D&A/Refinitiv (`03` §1): coverage, history depth,
  **display + redistribution rights**, price, API quality.
- Output: a recommendation memo appended to `03` and a procurement timeline; contract process initiated.
**Notes:** Decision (O2) can finalize near launch, but the *process* starts now (`03` §1, `09` §2).

### QV-011 — Compliance content draft: methodology + non-advice disclaimer `[PROD]` · `3pts` · Epic: EPIC-COMP · depends: —
**Story:** As product/compliance, I want the disclaimer + methodology copy drafted, so research-tool posture
is consistent across the UI/API.
**Acceptance criteria:**
- Draft "Methodology & Disclaimer" page; non-advice terminology guide (`07` §1).
- `disclaimer` field + `X-QuantVista-Disclaimer` header constants defined for the API (`04` §1).
**Notes:** Final copy gates public launch (Sprint 11).

**Sprint total:** ~58 pts · **Key risks:** IaC lead time (QV-008), procurement start (QV-010).

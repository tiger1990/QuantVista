---
baseline_commit: 4dfcc6b225cf748df7300c79a10cecf31549748f
---

# Story 2.4: QV-007 — Tenant-context middleware + Entitlement Service (stub)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the API platform**,
I want **a single place that resolves the caller's tenant, binds it to the RLS DB session, and answers entitlement checks against the seeded plan**,
so that **every downstream feature gates access and quotas consistently — without each route re-implementing tenant binding or plan logic**.

> Canonical ID **QV-007** · Epic 2 (EPIC-IDN) · `[BE]` · 5pts · Sprint 00 · depends: **QV-006 (done)**
> Authoritative detail: `plans/sprints/sprint-00-foundations.md` §QV-007. Tenancy/RLS: `plans/03-data-architecture.md`; entitlement error shape & envelope: `plans/04-api-contracts.md` §1.

## Acceptance Criteria

1. **Tenant-context resolution + DB binding** — A reusable dependency resolves the active tenant from the authenticated `Principal` (the `tenant_id` claim already on the access JWT) and provides a **tenant-bound DB session** that has `app.tenant_id` set for its transaction (via the existing `bind_tenant`/`session_scope(tenant_id)`), so Postgres RLS filters every query to that tenant. No raw `tenant_id` is read from request bodies/headers — only from the verified token.
2. **`IEntitlementService` concrete (stub, reads seed)** — `get(tenant_id)` returns the active tenant's plan **limits + capability flags** (read from `subscriptions → plans → entitlements`, the QV-005 seed). `is_allowed(tenant_id, feature)` returns the capability flag; `limit(tenant_id, key)` returns the numeric quota (`None` = unlimited/absent — document which). A missing subscription is handled gracefully (no crash; treated as no entitlements).
3. **`entitlement_exceeded` enforcement shape** — A reusable gate (dependency factory `require_entitlement(feature)`) raises a domain error mapped to the canonical **`entitlement_exceeded` (403)** envelope (`{ success:false, data:null, error:{code:"entitlement_exceeded", message} }`). A Free-plan tenant is **denied** a capability the Free plan lacks (e.g. `api_access`, `backtest`); a Quant-plan tenant is **allowed**.
4. **Cross-tenant isolation proven** — An integration test drives a request through the tenant-context dependency and shows a tenant **cannot read another tenant's rows** (RLS denial through the resolved/bound session). This is a **required CI RLS/authz gate**, not optional.
5. **Interfaces are final; implementation is a stub** — The `ITenantContext` / `IEntitlementService` shapes are finalized now (real Stripe-driven entitlement sync + Redis cache invalidation arrive Sprint 10, QV-074/075). No Stripe, no Redis caching, no plan-mutation endpoints in this story.
6. **No new migration; no schema change** — `tenants`/`subscriptions`/`plans`/`entitlements` already exist (migration `0002`) and are seeded (QV-005). This story adds **application/service code only**.
7. **No regressions** — all gates green: ruff, ruff format, mypy `--strict`, **import-linter** (DAG unchanged — new code lives in `identity` + `api`), pytest (incl. QV-004 RLS, QV-005 seed, QV-006 auth tests). New unit + integration tests run in the CI Postgres (`backend-rls`) job.

## Tasks / Subtasks

- [x] **Task 1 — Tenant context type + dependency** (AC: #1)
  - [x] Add a concrete `TenantContext` (frozen dataclass, `slots=True`) implementing the existing `ITenantContext` Protocol — carries `tenant_id` (+ `user_id`, `role` for convenience). Place in `quantvista/identity/tenant_context.py` (new) or `identity/models.py`; keep `ITenantContext` in `identity/interfaces.py`.
  - [x] In `quantvista/api/deps.py` add `get_tenant_context(principal: Principal = CurrentPrincipal) -> TenantContext` (derives from the verified JWT claims — never from request input).
  - [x] Add a `tenant_session` FastAPI dependency that **yields** a `session_scope(ctx.tenant_id)`-bound `Session` (RLS-enforced) for routes/services that read tenant tables. This is the "middleware" seam — a per-request, per-transaction binding consistent with `core/db.py` (do **not** write a heavyweight ASGI middleware that opens a request-spanning transaction; it breaks the per-transaction RLS model — see Dev Notes).
- [x] **Task 2 — EntitlementService (stub) + repo** (AC: #2,#5)
  - [x] Add a structured entitlements read to `quantvista/identity/repositories.py` that returns rows with **distinct** `key, limit_int, flag_bool` (do not collapse limit/flag — the existing `entitlements_for_tenant` is lossy and is for `/me` display only; keep it, add a new function e.g. `plan_entitlements(session, tenant_id) -> list[Row]`).
  - [x] Implement `EntitlementService` (concrete `IEntitlementService`) in `quantvista/identity/entitlements.py` (new): `get(tenant_id) -> Entitlements` (mapping view), `is_allowed(tenant_id, feature) -> bool` (capability flag truthy), `limit(tenant_id, key) -> int | None`, and `check(tenant_id, feature) -> None` (raises `EntitlementExceeded` when not allowed). Reads via a **tenant-bound** `session_scope(tenant_id)` (subscriptions/entitlements are RLS/global — confirm access path in Dev Notes).
  - [x] Define an `Entitlements` / `Entitlement` value type (frozen dataclass or typed mapping) in `identity/models.py`.
- [x] **Task 3 — `IEntitlementService` interface finalize** (AC: #2,#5)
  - [x] Update `quantvista/identity/interfaces.py`: extend `IEntitlementService` to the final surface (`get`, `is_allowed`, `limit`; optionally `check`). Keep it `@runtime_checkable`. This is the locked interface for QV-074/075.
- [x] **Task 4 — Enforcement gate + envelope mapping** (AC: #3)
  - [x] Add `EntitlementExceeded(Exception)` to `quantvista/identity/models.py` (carry the offending `feature`).
  - [x] Add `require_entitlement(feature: str)` dependency **factory** in `quantvista/api/deps.py` → resolves `TenantContext`, calls `EntitlementService.check`, raises `EntitlementExceeded` on denial.
  - [x] Register an exception handler in `quantvista/api/app.py` mapping `EntitlementExceeded` → `_fail("entitlement_exceeded", …)` (status 403 via existing `ERROR_STATUS`).
- [x] **Task 5 — Tests** (AC: all)
  - [x] **Unit** (no DB, fake session/repo): `is_allowed` true for a granted capability flag, false otherwise; `limit` returns the numeric quota and `None` for unlimited/absent; `check` raises `EntitlementExceeded`; `TenantContext` exposes the right `tenant_id`; `EntitlementExceeded` → `entitlement_exceeded`/403 mapping.
  - [x] **Integration** (`-m integration`, Postgres): register a tenant (Free plan) → `EntitlementService.get` returns the seeded Free entitlements; **`require_entitlement("api_access")` / `("backtest")` → 403 `entitlement_exceeded`** for Free; allowed for a Quant-plan tenant. **Cross-tenant RLS denial**: through `tenant_session`, tenant A cannot read tenant B's rows (use the QV-004 `two_tenants` fixture pattern). Mount any probe route on a **test-only** FastAPI app — do **not** add product routes.
  - [x] Reuse the QV-004/QV-006 harness: `conftest.py` reachability skip, `admin_engine`, `account`/`two_tenants` fixtures.
- [x] **Task 6 — Docs** (AC: #7)
  - [x] Update `backend/README.md` (tenant-context + entitlement gating pattern — how a route opts into RLS binding and feature gating). The CI `backend-rls` job already migrates + runs `-m integration`; new tests run there with no workflow change needed.

## Dev Notes

### Scope discipline
QV-007 = **tenant-context resolution/binding seam** + **EntitlementService stub** (reads the QV-005 seed) + **`entitlement_exceeded` gate**. **Deferred (not this story):** Stripe checkout/webhooks and real entitlement sync (QV-074/075, Sprint 10), Redis entitlement cache + webhook bust (`ent:{tenant_id}`), per-route enforcement of every gated feature (QV-076), tenant-switching / member-management, quota **counting** logic (e.g. "you have 3/3 watchlists") — that lands with each feature. Build the seam and prove it; don't wire product features.

### "Middleware" here means a FastAPI dependency, not ASGI middleware (critical — get this right)
The sprint card says "middleware", but the codebase binds RLS **per transaction** via `session_scope(tenant_id)` in `core/db.py` (`SET LOCAL app.tenant_id`, reset at commit/rollback). A request-spanning ASGI middleware that opens one long-lived transaction would fight that model and leak/serialize connections. Implement the tenant seam as **FastAPI dependencies** (`get_tenant_context`, `tenant_session`, `require_entitlement`) that resolve the tenant from the verified JWT and open a tenant-bound `session_scope` for the unit of work. This matches QV-006's `get_current_principal` dependency style.

### What already exists — REUSE, do not reinvent
- **`ITenantContext`** Protocol (`identity/interfaces.py`) — `tenant_id` property. Already defined; add the concrete impl.
- **`IEntitlementService`** Protocol (`identity/interfaces.py`) — currently only `is_allowed(tenant_id, feature) -> bool`. **Extend** it (don't create a parallel interface).
- **DB binding** (`core/db.py`): `bind_tenant(session, tenant_id)`, `session_scope(tenant_id)` (app role, RLS-enforced), `privileged_session_scope()` (admin, bypasses RLS). Use `session_scope(tenant_id)` for entitlement/tenant reads.
- **`entitlements_for_tenant(session, tenant_id)`** (`identity/repositories.py`) — returns a **lossy** `key → (limit or flag)` dict, used by `/me`. Keep it for display; add a **structured** query for the service so limit vs flag stays unambiguous (Pro `watchlist_items = (NULL,NULL)` means "unlimited", which the lossy dict can't distinguish from a false flag).
- **Envelope + codes** (`schemas/envelope.py`): `entitlement_exceeded` is **already** in `ERROR_STATUS` → **403**. `Envelope.fail(code, message)`. Reuse `_fail(...)` in `api/app.py`.
- **Error-handler pattern** (`api/app.py`): see `EmailAlreadyExists`/`InvalidCredentials` handlers — copy that shape for `EntitlementExceeded`.
- **Principal + JWT claims** (`identity/models.py`, `api/deps.py`): the access token carries `sub` (user) + `tenant_id` + `role`; `get_current_principal` already decodes it. Resolve tenant from `Principal.tenant_id` — never from client input.
- **Seed (QV-005)** — `backend/src/quantvista/db/seeds/seed_reference.sql`. Free: `saved_screens=3, watchlists=1, watchlist_items=10, alerts=3, backtest=false, api_access=false`. Quant: most unlimited (`NULL`), `backtest=true, backtest_full=true, api_access=true`. These are the values your integration assertions check.

### Entitlements data model & access path
- Tables (migration `0002`): `plans(code ∈ {free,pro,quant})` **[global]**, `entitlements(plan_id, key, limit_int, flag_bool, UNIQUE(plan_id,key))` **[global]**, `subscriptions(tenant_id, plan_id, status, …)` **[RLS, tenant-scoped]**. The join `subscriptions → plans → entitlements` for a tenant **crosses an RLS table** (`subscriptions`). Read it via `session_scope(tenant_id)` so RLS resolves the tenant's own subscription; `plans`/`entitlements` are global and join freely. (Mirror how `me()` does it: `repo.entitlements_for_tenant` runs inside `session_scope(principal.tenant_id)`.)
- **Semantics to document:** `limit_int = NULL` ⇒ unlimited; `flag_bool` ⇒ capability on/off. A key absent for a plan ⇒ not granted. Decide and document what `is_allowed` returns for a limit-type key (recommend: `True` if the key exists / limit is non-zero; quota *counting* is enforced per-feature later).

### Module boundaries / DAG (import-linter — must stay green)
- New service + context code is **`identity`** (foundational layer; imported by all, imports only `core`/`schemas`). The enforcement **dependencies/handlers** are **`api`** (composition root; may import `identity`). This keeps the layered DAG in `backend/.importlinter` intact — no new edges beyond the existing `api → identity → core/schemas`.
- Do **not** import another context's internals; entitlement reads go through the `identity` repo/service only.

### Critical constraints (project-context)
- Tenant isolation is **Postgres RLS, not app code** — every tenant read must run inside a `SET LOCAL app.tenant_id` transaction. The gate must not "trust" `tenant_id` from anywhere but the verified JWT.
- **Every tenant-scoped feature needs a cross-tenant-denial test** — AC #4 is that test for this seam (required CI gate).
- Modern typing, `from __future__ import annotations`; mypy `--strict` on public interfaces; financial values `Decimal` (n/a here). Many small files (200–400 lines).
- **No secrets, no new deps** — this is pure app code over existing infra. If you think you need a new dependency, stop and raise it.

### Testing standards
- Unit tests run with **no DB** (fake the repo/session boundary). Integration tests (`-m integration`) need Postgres (local or CI). AAA structure, behavior-named (`test_free_plan_denied_api_access`, `test_tenant_cannot_read_other_tenants_rows`). Coverage **≥80%** on new `identity`/`api` code.
- For the RLS denial + gate, mount a **throwaway** FastAPI app/route inside the test that `Depends(tenant_session)` / `Depends(require_entitlement(...))`. Don't add product endpoints to ship this story.
- Reuse `two_tenants` (QV-004) for the cross-tenant read test and the `account` fixture (QV-006) for plan-based gate tests; tear down via tenant cascade.

### Project Structure Notes
- **New:** `backend/src/quantvista/identity/entitlements.py` (EntitlementService); `backend/src/quantvista/identity/tenant_context.py` (TenantContext) *(or fold TenantContext into `identity/models.py`)*; `backend/tests/test_entitlements.py` (unit); `backend/tests/integration/test_tenant_context.py` (RLS denial + gate).
- **Modified:** `backend/src/quantvista/identity/interfaces.py` (finalize `IEntitlementService`); `identity/models.py` (`EntitlementExceeded`, `Entitlements`); `identity/repositories.py` (structured entitlements query); `backend/src/quantvista/api/deps.py` (`get_tenant_context`, `tenant_session`, `require_entitlement`); `backend/src/quantvista/api/app.py` (`EntitlementExceeded` handler); `backend/README.md`.
- **Unchanged:** no migration, no `pyproject.toml` deps, no CI workflow edits.

### References
- [Source: plans/sprints/sprint-00-foundations.md#QV-007] — middleware resolves tenant from principal + binds DB session; `IEntitlementService.get(tenant)` reads seed; `entitlement_exceeded` shape; interface final, Stripe sync in Sprint 10
- [Source: plans/04-api-contracts.md#1] — canonical error codes incl. `entitlement_exceeded`; standard envelope
- [Source: plans/03-data-architecture.md] — RLS, `SET LOCAL app.tenant_id`, `app_current_tenant()`
- [Source: backend/src/quantvista/core/db.py] — `bind_tenant`, `session_scope(tenant_id)`, `privileged_session_scope`
- [Source: backend/src/quantvista/identity/interfaces.py] — existing `ITenantContext`, `IEntitlementService` Protocols to extend
- [Source: backend/src/quantvista/identity/repositories.py#entitlements_for_tenant] — entitlements join + lossy dict (display)
- [Source: backend/src/quantvista/identity/services.py#me] — reference access path for entitlement reads (tenant-bound session)
- [Source: backend/src/quantvista/schemas/envelope.py] — `entitlement_exceeded → 403`, `Envelope.fail`
- [Source: backend/src/quantvista/api/app.py] — domain-error → envelope handler pattern
- [Source: backend/src/quantvista/db/seeds/seed_reference.sql] — Free/Pro/Quant entitlement values (assertion targets)
- [Source: backend/.importlinter] — layered DAG (`api → identity → core/schemas`)
- [Source: _bmad-output/implementation-artifacts/2-3-qv-006-authn-register-login-jwt-refresh-rotation.md] — `Principal`/JWT claims, `get_current_principal`, test harness, error-handler wiring
- [Source: _bmad-output/project-context.md] — RLS not app code; cross-tenant denial test required; no new deps/secrets

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Opus 4.8) via BMAD dev-story workflow.

### Debug Log References

- **`require_entitlement` return typing:** `fastapi.Depends()` is typed to return `Any` (it's a
  default-value sentinel), so `mypy --strict` flagged `no-any-return` against the `-> params.Depends`
  annotation. Fixed with `cast(params.Depends, Depends(_require))` — keeps the factory's signature
  honest without loosening the return type.
- **Tenant-session dependency wiring:** the probe route initially used the bare `get_tenant_session`
  function as a default, which FastAPI treats as a literal value, not a dependency. Switched to the
  exported `TenantSessionDep = Depends(get_tenant_session)`.
- No DB schema work: confirmed `plans`/`entitlements`/`subscriptions` (migration `0002`) + the QV-005
  seed already provide everything — **no new migration**.

### Completion Notes List

- **All 7 ACs satisfied; all tasks/subtasks complete. Status → review.** Gates green locally on
  PG 18: ruff, ruff format, mypy `--strict` (46 files), import-linter (3 contracts kept — DAG
  intact), pytest **51 passed** (+12 new: 8 unit, 4 integration). New-code coverage 93%
  (`identity/entitlements.py` 94%, `api/deps.py` 92%).
- **Tenant seam = FastAPI dependencies** (not ASGI middleware), matching the per-transaction RLS
  model: `get_tenant_context` (tenant from verified JWT only), `get_tenant_session`/`TenantSessionDep`
  (binds `app.tenant_id` → RLS-filtered session), `require_entitlement("feature")` (403 gate).
- **`EntitlementService` (stub)** reads the QV-005 seed via a tenant-bound session: `get`,
  `is_allowed`, `limit`, `check`. New **structured** repo query `plan_entitlements` keeps `limit_int`
  vs `flag_bool` distinct (the lossy `entitlements_for_tenant` is left for `/me` display).
  Semantics: capability key → its flag; limit-type key present (number or unlimited) → granted;
  absent key → not granted.
- **`IEntitlementService` finalized** to `get`/`is_allowed`/`limit`/`check` (locked for QV-074/075).
  **`EntitlementExceeded`** domain error + `api/app.py` handler → canonical `entitlement_exceeded`/403
  envelope.
- **Cross-tenant isolation proven *through the dependency*** (`test_tenant_context.py`): tenant A's
  request sees only A's rows, B's only B's. Entitlement gate: Free plan denied `api_access`/`backtest`
  (403), Quant allowed. Reused the QV-004 `two_tenants` + QV-006 `admin_engine` harness; added a
  `tenant_on_plan` factory fixture (admin-seeded, cascade-cleaned). Probe routes are test-only — no
  product endpoints added.
- **Deferred (per scope):** Stripe sync (QV-074/075), Redis `ent:{tenant_id}` cache + webhook bust,
  per-feature quota counting, per-route enforcement pass (QV-076). **No new deps, no secrets, no
  migration, no CI workflow change** (existing `backend-rls` job runs the new `-m integration` tests).

### File List

**New:**
- `backend/src/quantvista/identity/entitlements.py`
- `backend/tests/test_entitlements.py`
- `backend/tests/integration/test_tenant_context.py`

**Modified:**
- `backend/src/quantvista/identity/models.py` (`TenantContext`, `Entitlement`, `Entitlements`, `EntitlementExceeded`)
- `backend/src/quantvista/identity/interfaces.py` (finalize `IEntitlementService`)
- `backend/src/quantvista/identity/repositories.py` (`plan_entitlements`)
- `backend/src/quantvista/api/deps.py` (`get_tenant_context`, `get_tenant_session`, `get_entitlement_service`, `require_entitlement` + `*Dep` exports)
- `backend/src/quantvista/api/app.py` (`EntitlementExceeded` → `entitlement_exceeded` handler)
- `backend/README.md` (tenant-context & entitlement gating section)
- this story file; `sprint-status.yaml`

## Change Log

| Date | Change |
|------|--------|
| 2026-06-21 | QV-007 implemented: dependency-based tenant-context seam (`get_tenant_context`, `get_tenant_session` binding `app.tenant_id`), `EntitlementService` stub reading the QV-005 seed (`get`/`is_allowed`/`limit`/`check`), `require_entitlement` gate → `entitlement_exceeded` (403). `IEntitlementService` finalized; new `plan_entitlements` repo query. No migration/deps. Verified on local PG 18 — 51 tests (+12), all gates green. Status → review. |
| 2026-06-21 | Reconcile: PR #10 merged to `master` (`8687d16`); CI green (backend lint/types/imports, tests, RLS/seed/auth). Status review → **done**. |

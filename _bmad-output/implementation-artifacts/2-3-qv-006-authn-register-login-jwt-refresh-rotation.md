---
baseline_commit: 1d430790ce2fad101a5fa1fe32942c45cf649c5c
---

# Story 2.3: QV-006 — AuthN: register / login / JWT + refresh rotation

Status: review

## Story

As a **user**,
I want **to register and log in securely (email + password), receive a short-lived access token and a rotating refresh token, and read my profile**,
so that **I can access the platform with credentials that are safe at rest and resistant to token theft/replay**.

> Canonical ID **QV-006** · Epic 2 (EPIC-IDN) · `[BE]` · 8pts · Sprint 00 · depends: **QV-004 (done)**
> Authoritative detail: `plans/sprints/sprint-00-foundations.md` §QV-006. Auth: `plans/07-security-and-compliance.md` §2; tokens/contracts: `plans/04-api-contracts.md` §1.

## Acceptance Criteria

1. **Register** — `POST /api/v1/auth/register` `{ email, password, name }` creates **a tenant + an owner user + a Free-plan subscription** atomically: password hashed with **Argon2id**; `memberships.role = 'owner'`; an **email-verification stub** (token generated + logged, no real email send). Duplicate email → `conflict` envelope.
2. **Login** — `POST /api/v1/auth/login` `{ email, password }` verifies the Argon2id hash and issues a **short-lived access JWT (~15 min)** + a **rotating refresh token**. For web, the refresh token is set in an **httpOnly, Secure, SameSite cookie**; the response body carries the access token. Bad creds → `unauthenticated`.
3. **Refresh rotation + reuse detection** — `POST /api/v1/auth/refresh` issues a new access + new refresh token and **invalidates the presented one** (rotation). Presenting an already-used/revoked refresh token is detected as **reuse → the whole token family is revoked** (forces re-login). `POST /api/v1/auth/logout` revokes the current session.
4. **`GET /api/v1/me`** returns the authenticated **user + active tenant + entitlements summary** (the active tenant's plan entitlements), behind a Bearer access token; missing/invalid token → `unauthenticated`.
5. **Security correctness** — passwords never stored or logged in plaintext; refresh tokens stored **hashed** (never raw); access JWT signed and verified; tokens carry `sub` (user) + `tenant_id` (active tenant) + `exp`; secrets come from config/env (no hardcoded secret in prod).
6. **New migration `0013`** (expand-only, forward-only) adds a **`refresh_tokens`** table (global identity table — `user_id`, `family_id`, `token_hash`, `issued_at`, `expires_at`, `revoked_at`, `replaced_by`, …). No `tenant_id` → no RLS (auth runs before tenant context; a user spans tenants).
7. **No regressions** — all gates green (ruff, mypy --strict, import-linter, pytest incl. QV-004 RLS + QV-005 seed tests); new auth integration tests run in the CI Postgres job.

## Tasks / Subtasks

- [x] **Task 1 — Dependencies + config** (AC: #1,#2,#5) — _new deps, see "Approved dependencies"_
  - [x] Add `argon2-cffi` and `pyjwt` to `[project.dependencies]` in `backend/pyproject.toml`.
  - [x] Extend `quantvista/core/config.py`: `jwt_secret` (env; local dev default ok, **must be set in prod**), `jwt_algorithm = "HS256"`, `access_token_ttl_seconds = 900`, `refresh_token_ttl_seconds = 2592000` (30d), `cookie_secure = True`, `cookie_samesite = "lax"`, `refresh_cookie_name = "qv_refresh"`.
- [x] **Task 2 — Migration `0013`: refresh_tokens** (AC: #6)
  - [x] New Alembic revision `0013_auth_refresh_tokens` (down_revision `0012`): `refresh_tokens(id uuid pk default gen_random_uuid(), user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, family_id uuid NOT NULL, token_hash text NOT NULL, issued_at timestamptz NOT NULL default now(), expires_at timestamptz NOT NULL, revoked_at timestamptz, replaced_by uuid REFERENCES refresh_tokens(id), user_agent text, created_at timestamptz NOT NULL default now())`; UNIQUE `(token_hash)`; indexes on `user_id`, `family_id`. **No `tenant_id`, no RLS** (global identity). Hand-written, naming convention per `env.py`.
- [x] **Task 3 — Security helpers** (AC: #1,#2,#5)
  - [x] `quantvista/identity/security.py`: Argon2id `hash_password`/`verify_password` (argon2-cffi `PasswordHasher`); `create_access_token(user_id, tenant_id, role)`/`decode_access_token` (PyJWT, HS256, `exp`/`iat`/`type`); `new_refresh_token()` → `(raw, token_hash)` (opaque `secrets.token_urlsafe`, SHA-256 hash stored).
- [x] **Task 4 — Identity service (IAuthService impl)** (AC: #1,#2,#3,#4)
  - [x] Implement `IAuthService` in `quantvista/identity/services.py` + repositories in `repositories.py`:
    - `register(email, password, name)` → **privileged transaction** (admin engine bypasses RLS): insert tenant, user (global), membership(owner), Free-plan subscription; hash password; create verification token (stub-log). Duplicate email → domain conflict.
    - `authenticate(email, password)` → verify hash; on success mint access JWT + persist a new refresh-token row (new `family_id`); return tokens.
    - `refresh(raw_refresh)` → look up by hash; if missing/revoked/expired **or already replaced → reuse**: revoke entire `family_id`, raise. Else rotate: revoke old (`revoked_at`, `replaced_by`), insert new in same family, mint new access.
    - `logout(raw_refresh)` → revoke that token (and/or family).
    - `me(user_id, tenant_id)` → user + active tenant + entitlements summary (read subscription→plan→entitlements; tenant-scoped reads via `session_scope(tenant_id)`).
- [x] **Task 5 — API routers + cookie** (AC: #1,#2,#3,#4)
  - [x] `quantvista/api/` routers under `/api/v1`: `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/me`. Mount in `api/app.py`. All responses use the standard `Envelope`.
  - [x] Wire request/response DTOs (Pydantic) in `quantvista/schemas/` (so the generated TS client picks them up): `RegisterRequest`, `LoginRequest`, `TokenResponse{access_token,token_type}`, `MeResponse`.
  - [x] Web refresh handling: set/read the refresh token in the **httpOnly/Secure/SameSite** cookie; `/auth/refresh` and `/auth/logout` read it from the cookie (or body for API clients).
  - [x] A `get_current_user` FastAPI dependency: parse `Authorization: Bearer`, decode/verify the access JWT → `(user_id, tenant_id, role)`; invalid → `unauthenticated` (401).
- [x] **Task 6 — Tests** (AC: all)
  - [x] **Unit** (no DB): Argon2id hash≠plaintext + verify round-trip; JWT encode/decode + expiry rejected; refresh-hash helper; envelope error codes.
  - [x] **Integration** (`-m integration`, Postgres): register→login→`/me` happy path; duplicate-email → `conflict`; bad creds → `unauthenticated`; **refresh rotation** (old token rejected after rotation); **reuse detection** (replaying a rotated token revokes the family → subsequent refresh fails); `/me` entitlements reflect the Free plan. Tear down created tenant/user (cascade).
  - [x] Reuse the QV-004 harness (`conftest.py` reachability skip, `admin_engine`).
- [x] **Task 7 — CI + docs** (AC: #7)
  - [x] CI `backend-rls`/DB job already migrates + runs `-m integration`; ensure migration `0013` + auth tests run there. Update `backend/README.md` (auth flow, token model) and `db/README.md` (refresh_tokens table note).

## Dev Notes

### Scope discipline
QV-006 = **email + password** register/login + JWT access + **rotating refresh with reuse detection** + `/me`. **Deferred (not this story):** TOTP MFA (the `users.mfa_enabled` column exists but stays false), Google OAuth/SSO (`07` §2), Quant-tier **API keys** (QV-077), real email delivery (stub here), tenant-switching UI, member management endpoints. Don't build them.

### Approved dependencies (new — explicitly authorized by this story)
- **`argon2-cffi`** — Argon2id password hashing (project-context Conventions: "Argon2id password hashing"). Use `argon2.PasswordHasher` (Argon2id is its default).
- **`pyjwt`** — access-token signing/verification (HS256). These are declared in `pyproject` and installed by the Dockerfile/CI (`pip install .[dev]`). No other new deps without raising it.

### What already exists (build on it)
- **Schema (migrations 0001–0012, applied):** `tenants(id,name,type,status,…)` **[RLS]**, `users(id,email,password_hash,name,status,mfa_enabled,…)` **[global, no RLS]**, `memberships(id,tenant_id,user_id,role)` **[RLS]**, `memberships.role ∈ {owner,admin,member}**, `subscriptions(id,tenant_id,plan_id,stripe_subscription_id,status,current_period_end)` **[RLS]**, `plans`/`entitlements` **[global]**. **No session/refresh table exists** → Task 2 adds `refresh_tokens` (0013).
- **QV-004 DB layer (`quantvista/core/db.py`):** `session_scope(tenant_id)` (app role, RLS-enforced) and `privileged_session_scope()` (admin role, bypasses RLS). **Register must use the privileged path** — it creates a `tenants` row (RLS `WITH CHECK id = app_current_tenant()`) plus `memberships`/`subscriptions` (RLS) before any tenant context exists; the admin engine bypasses RLS for this identity bootstrap. Tenant-scoped reads in `/me` (subscription) use `session_scope(tenant_id)`.
- **QV-005 seed:** Free/Pro/Quant plans + entitlements exist; register attaches the **Free** plan (`plans.code='free'`) subscription.
- **Response envelope** (`quantvista/schemas/envelope.py`) + canonical error codes: `validation_error`(422), `unauthenticated`(401), `forbidden`(403), `conflict`(409). Reuse — don't invent shapes.
- **Test harness (QV-004):** `conftest.py` skips integration tests without Postgres; `admin_engine` fixture seeds/tears down; `integration` marker; CI `backend-rls` job runs migrations + `pytest -m integration` against a Postgres service.
- **import-linter:** `identity` is foundational (depended on by all; imports no domain context). `api` may import `identity` + `schemas`. New imports of `argon2`/`jwt` are external — DAG stays green.

### Token & rotation design (security-critical — get this right)
- **Access token:** signed JWT (HS256, `jwt_secret`), claims `{ sub: user_id, tenant_id, role, type:"access", iat, exp(~15m) }`. Verified on every protected request via `get_current_user`.
- **Refresh token:** **opaque** random string (`secrets.token_urlsafe(32)`), returned to the client (cookie for web), **stored only as a SHA-256 hash** with a `family_id`. Never a JWT, never stored raw.
- **Rotation:** each `/auth/refresh` issues a new refresh token in the **same family**, sets the old row's `revoked_at` + `replaced_by`. Normal clients always present the latest token.
- **Reuse detection:** if a presented token is unknown, expired, already `revoked_at`/`replaced_by` set → treat as **theft**; revoke **every** token in that `family_id` (`UPDATE … WHERE family_id = :fid AND revoked_at IS NULL`) and return `unauthenticated`. This is the headline security behavior — test it explicitly.
- **Cookie:** `Set-Cookie: qv_refresh=…; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth; Max-Age=…`. (`cookie_secure` configurable so local http works if needed.)

### Critical constraints (project-context)
- **Argon2id** for passwords; financial values `Decimal` (n/a here). Modern typing, `from __future__ import annotations`.
- **No secrets in source:** `jwt_secret` from env; a dev default is fine locally but document that prod must set it (and fail fast if missing in non-local env is a nice-to-have).
- **Two domains:** `users`/`refresh_tokens`/`plans`/`entitlements` are global; `tenants`/`memberships`/`subscriptions` are tenant-scoped RLS. Respect the access paths above.
- **Migrations:** forward-only, expand-only (add table) — no edits to 0001–0012; RLS not added (refresh_tokens is global). Keep the `ix_/uq_/fk_/pk_` naming convention.

### Testing standards
- Unit tests run with **no DB**. Integration tests (`-m integration`) need Postgres (local or CI) — they exercise the real flows + the reuse-detection family revoke (the mandatory security behavior). AAA, behavior-named. Coverage ≥80% on new `identity` + `api` auth code.
- Do **not** assert on raw tokens in logs; assert hashes/rows in `refresh_tokens` for rotation/reuse.

### Project Structure Notes
- New: `backend/src/quantvista/db/migrations/versions/0013_auth_refresh_tokens.py`; `quantvista/identity/security.py`; auth router module under `quantvista/api/`; `quantvista/schemas/auth.py`; `backend/tests/integration/test_auth.py` + unit `backend/tests/test_auth_security.py`.
- Modified: `quantvista/identity/{services,repositories,interfaces}.py` (flesh out `IAuthService`), `quantvista/api/app.py` (mount routers), `quantvista/core/config.py`, `backend/pyproject.toml`, READMEs.

### References
- [Source: plans/sprints/sprint-00-foundations.md#QV-006]
- [Source: plans/07-security-and-compliance.md#2-authentication] — Argon2id, ~15m access + rotating refresh, httpOnly cookie, reuse detection → revoke family
- [Source: plans/04-api-contracts.md#1] — Bearer access, refresh rotation, `/auth/*`, `/me`
- [Source: backend/src/quantvista/db/migrations/versions/0002_identity_tenancy_billing.py] — tenants/users/memberships/subscriptions + RLS
- [Source: _bmad-output/implementation-artifacts/2-1-qv-004-postgresql-alembic-rls-scaffolding.md] — `session_scope`/`privileged_session_scope`, integration harness
- [Source: _bmad-output/project-context.md#conventions] — Argon2id; short access JWT + rotating refresh + reuse detection

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Opus 4.8) via BMAD dev-story workflow.

### Debug Log References

- **Security bug caught by the reuse test:** the family-revoke on reuse was being **rolled back** —
  `rotate()` revoked the family inside `session_scope()` then `raise`d *inside* the `with`, so the
  context manager rolled the revoke back (family never revoked; the live token still worked).
  Fixed by doing all writes inside the transaction and **raising only after it commits** (flags
  `reuse`/`expired` set inside, raised after the block).
- **Refresh cookie not sent in tests:** the cookie is `Secure` (correct default), but `TestClient`
  defaults to `http://` → httpx won't send it. Fixed the test client to use `https://testserver`;
  added `COOKIE_SECURE=false` to `.env.example` so the real local stack works over http.
- ruff B008 on FastAPI `Depends()` defaults → added `flake8-bugbear extend-immutable-calls`.
- mypy `no-any-return` on `.scalar_one()` (typed `Any`) returned as `UUID` → `cast(UUID, …)`.
- PyJWT `InsecureKeyLengthWarning` → lengthened the dev `jwt_secret` default to ≥32 bytes.

### Completion Notes List

- **All 7 ACs satisfied; all tasks complete. Status → review.** Gates green: ruff, ruff format,
  mypy --strict, import-linter (new `api→identity→core/schemas` edges allowed), pytest **39 passed**
  (4 new auth-unit + 3 new auth-integration) against local PG 18.4.
- **Migration `0013`** adds `refresh_tokens` (global identity, no RLS; hashed tokens + `family_id`).
- **Security helpers** (`identity/security.py`): Argon2id hash/verify, HS256 access JWT
  encode/decode (+ `type` check), opaque refresh token + SHA-256 hashing.
- **`AuthService`** (`identity/services.py` + `repositories.py`): `register` (privileged tx → tenant
  + owner user + Free subscription, Argon2id, email-verification **stub-logged**), `authenticate`,
  `issue_tokens`, `rotate` (rotation + **reuse → revoke family**), `logout`, `me`.
- **API** (`api/routes.py`, `deps.py`, `app.py`): `/auth/register|login|refresh|logout` + `/me`,
  standard envelope, httpOnly/Secure/SameSite refresh cookie, `get_current_principal` Bearer
  dependency, and domain-error → envelope-code handlers (`conflict`/`unauthenticated`/`validation_error`).
- **Tests:** unit (hash≠plaintext, JWT round-trip + expiry, refresh hashing) + integration
  (register→`/me` happy path with Free-plan entitlements; duplicate→409; bad creds→401;
  **refresh rotation**; **reuse detection revokes the family**). Cleanup drops tenant+user (cascade).
- **`IAuthService` interface** updated to the real surface; `.env.example`/README/`db/README`/CI
  job-name updated. CI `backend-rls` (renamed *"Backend DB (RLS, seed, auth)"*) runs migration `0013`
  + auth integration tests against the Postgres service.
- **Approved deps added:** `argon2-cffi`, `pyjwt`. **Deferred (per scope):** MFA, OAuth/SSO, API
  keys (QV-077), real email delivery.

### File List

**New:**
- `backend/src/quantvista/db/migrations/versions/0013_auth_refresh_tokens.py`
- `backend/src/quantvista/identity/security.py`
- `backend/src/quantvista/schemas/auth.py`
- `backend/src/quantvista/api/deps.py`, `backend/src/quantvista/api/routes.py`
- `backend/tests/test_auth_security.py`, `backend/tests/integration/test_auth.py`

**Modified:**
- `backend/src/quantvista/identity/{interfaces,models,services,repositories}.py`
- `backend/src/quantvista/api/app.py` (mount auth routes + error handlers)
- `backend/src/quantvista/core/config.py` (jwt/cookie settings)
- `backend/pyproject.toml` (argon2-cffi, pyjwt; ruff flake8-bugbear immutable-calls)
- `.env.example` (JWT/cookie vars), `.github/workflows/ci.yml` (job rename)
- `backend/README.md`, `backend/src/quantvista/db/README.md`
- this story file; `sprint-status.yaml`

## Change Log

| Date | Change |
|------|--------|
| 2026-06-20 | QV-006 implemented: email+password auth — Argon2id hashing, HS256 access JWT (~15m), opaque rotating refresh (hashed, `family_id`) with **reuse-detection family-revoke**, httpOnly/Secure cookie, `/auth/*` + `/me`. New migration `0013` (`refresh_tokens`), deps `argon2-cffi`+`pyjwt`. Verified on local PG 18.4 (39 tests incl. 3 auth-integration). Status → review. |

---
baseline_commit: 0d599987c38ca114eb741277e21e9d003fc70fa9
---

# Story 4.12: QV-039 — Saved screens (entitlement-limited)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **to save screens**,
so that **I reuse them**.

> Canonical ID **QV-039** · Epic 4 (EPIC-INTEL) · `[BE]` · 3pts · depends: **QV-038 ✅** (screener DSL), **QV-007 ✅** (entitlements)
> Authoritative: `04` §3.4 (`POST /screens { name, criteria }`, entitlement-limited) · `01` §4 (tier limits) · **US-06** (`entitlement_exceeded`).

## What exists (reuse)

- **Screener DSL** (`analytics/screener.py`, QV-038) — `build_where`/`build_order` validate a filter/sort spec against the allow-list. Reused to **validate `criteria` at save time** (never persist an unrunnable screen).
- **Entitlement** — the **`saved_screens`** key is **already seeded** (Free = 3, Pro = 25, Quant = unlimited). `EntitlementService.limit(tenant_id, "saved_screens")` → `int | None`. `EntitlementExceeded` → 403 `entitlement_exceeded` (handler exists).
- **RLS tenant pattern** — `0011_backtests` (tenant-scoped table + `ENABLE/FORCE ROW LEVEL SECURITY` + `POLICY … USING (tenant_id = app_current_tenant())`); `get_tenant_session` (SET LOCAL app.tenant_id → RLS-scoped unit of work). New tables auto-grant to the app role (as backtests does).
- **Envelope + auth + entitlement service** — `Envelope`, `get_current_principal`, `get_tenant_context`, `get_tenant_session`, `get_entitlement_service`, `ERROR_STATUS` (`entitlement_exceeded`/`conflict`/`not_found`/`validation_error`) — QV-032/033/038.

## Locked decisions

- **Migration `0014_saved_screens`** (mirror `0011_backtests`): `id, tenant_id → tenants(ON DELETE CASCADE), user_id → users, name text, criteria jsonb, created_at`; `UNIQUE (tenant_id, name)`; `ix_saved_screens_tenant_id`; `ENABLE + FORCE RLS` + `saved_screens_isolation` policy (`USING/WITH CHECK tenant_id = app_current_tenant()`).
- **Criteria** = the runnable screener spec, stored as jsonb: `{ market, filters: [{field, op, value}], sort }` (no `limit`/`cursor` — those are runtime). **Validated on save** via `build_where(filters)` + `build_order(sort)` → invalid field/op/value → **422 `validation_error`** (the same allow-list defence; never store a screen that can't run).
- **Endpoints (auth, RLS tenant session):**
  - `POST /api/v1/screens { name, criteria }` → **entitlement check** (`count(saved_screens) < limit`, NULL = unlimited; else **403 `entitlement_exceeded`**) → validate criteria → insert → **201** `Envelope[SavedScreen]`. Duplicate name (UNIQUE) → **409 `conflict`**.
  - `GET /api/v1/screens` → `Envelope[list[SavedScreen]]` (tenant's, newest first).
  - `DELETE /api/v1/screens/{id}` → **204** (RLS-scoped; unknown/other-tenant id → **404 `not_found`**).
- **Running a saved screen = re-POST its `criteria` to `/screener`** — no separate run endpoint (the criteria *is* a `/screener` body). Keeps the story at 3pts.
- **Isolation via RLS** — all reads/writes on `get_tenant_session`; the policy guarantees a tenant sees only its own screens (a cross-tenant `DELETE`/`GET` simply finds nothing). `tenant_id`/`user_id` from the verified principal, never the body.
- **Placement:** repo `analytics/saved_screens.py` (`create`/`list`/`count`/`delete`); DTOs `schemas/screens.py`; route `api/routes_screens.py`; migration `db/migrations/versions/0014_saved_screens.py`.

## Acceptance Criteria

1. **Table + RLS.** `0014_saved_screens` — tenant-scoped, RLS `app_current_tenant()` policy, `UNIQUE(tenant_id, name)`; `alembic upgrade` + `downgrade` clean.
2. **Create.** `POST /screens` validates the criteria via the allow-list (invalid → 422), enforces the `saved_screens` tier limit (over → 403 `entitlement_exceeded`), rejects a duplicate name (→ 409 `conflict`), and returns 201 with the stored screen.
3. **List / delete.** `GET /screens` returns the tenant's screens; `DELETE /screens/{id}` removes one (204) and is RLS-isolated (another tenant's id → 404).
4. **Isolation.** All ops on the RLS tenant session; `tenant_id`/`user_id` from the principal. A test proves tenant B cannot see/delete tenant A's screen.
5. **Boundaries.** Repo in `analytics`; DTOs in `schemas`; route in `api`. `lint-imports` green.
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` (≥80% new code) green. **Integration** (real PG + auth, 2 tenants): create+list+delete round-trip; **limit → 403** (save up to the Free cap of 3, the 4th fails); **invalid criteria → 422**; **duplicate name → 409**; **cross-tenant isolation**.

## Tasks / Subtasks

- [x] **Task 1 — migration** (AC: #1)
  - [x] `0014_saved_screens.py` (revision 0014, down 0013): create table + index + RLS enable/force + isolation policy; `downgrade` drops it. Apply locally (`alembic upgrade head`).
- [x] **Task 2 — repo + DTOs** (AC: #2, #3)
  - [x] `analytics/saved_screens.py`: `create_saved_screen(session, tenant_id, user_id, name, criteria) -> dict`, `list_saved_screens(session) -> list[dict]`, `count_saved_screens(session) -> int`, `delete_saved_screen(session, screen_id) -> bool` (RLS-scoped). `schemas/screens.py`: `ScreenCriteria` (market, filters:[FilterClause], sort), `SaveScreenRequest` (name, criteria), `SavedScreen` (id, name, criteria, created_at).
- [x] **Task 3 — route** (AC: #2, #3, #4, #5)
  - [x] `api/routes_screens.py`: POST/GET/DELETE `/screens` on `get_tenant_session`; entitlement via `EntitlementService.limit`; criteria validated via `build_where`/`build_order`; `IntegrityError` (dup name) → 409; unknown id → 404. Register in `app.py`; a `ScreenNotFound` (or reuse) → 404 handler.
- [x] **Task 4 — tests + gates + reconcile** (AC: #6)
  - [x] `tests/integration/test_api_screens.py` (real PG + 2 registered tenants). Run gates. Reconcile QV-038 → done (already applied).

## Dev Notes

### Entitlement check (US-06)
```python
limit = entitlements.limit(ctx.tenant_id, "saved_screens")   # Free 3 / Pro 25 / Quant None
if limit is not None and count_saved_screens(session) >= limit:
    raise EntitlementExceeded("saved_screens")               # → 403 entitlement_exceeded
```
Count is RLS-scoped (tenant's own screens only). Race on the limit under concurrency is acceptable (a soft cap; the UNIQUE + the check are best-effort — same posture as other counted entitlements).

### Criteria validation (reuse QV-038)
`build_where(criteria.filters)` + `build_order(criteria.sort)` — `ScreenerError` → 422. Store `criteria.model_dump()` as jsonb. On GET, return it as-is (a valid `/screener` body sans `limit`/`cursor`).

### RLS
Mirror `0011_backtests` exactly. All queries on `get_tenant_session` → the `app_current_tenant()` policy scopes them; no manual `WHERE tenant_id=` needed for isolation (but the INSERT sets `tenant_id` for the `WITH CHECK`). Cross-tenant `DELETE` affects 0 rows → 404.

### Boundaries
Repo in `analytics` (screener-adjacent, reuses the DSL); entitlement read via `identity` `EntitlementService`; route composes. **Not this story:** a run endpoint (re-POST criteria to `/screener`), the screener/screens UI (QV-040), sharing/duplicating screens, screen folders.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** `ruff` + `ruff format --check` clean · `mypy --strict` Success (163 files) · `lint-imports`
  3/3 · full `pytest` **325 passed / 4 skipped**. Coverage: `analytics/saved_screens.py`,
  `api/routes_screens.py`, `schemas/screens.py` all **100%** (95% overall).
- **QV-039 tests:** 5 integration (real PG + auth, 2 tenants) — round-trip, **403 at the Free cap of 3**,
  **422 invalid criteria**, **409 duplicate name**, **cross-tenant isolation** (B sees none / delete → 404).
- **Migration correction (CI caught it):** `saved_screens` is **already created by `0009_watchlists_screens`**
  (with the GIN index on `criteria` + RLS). My first `0014` mistakenly did `CREATE TABLE` again → passed
  locally only because I'd earlier dropped the 0009 table thinking it was a stray, but **collided on CI's
  fresh DB** ("relation already exists"). **Fixed:** `0014_saved_screen_unique_name` now only
  `ALTER TABLE saved_screens ADD CONSTRAINT uq_saved_screens_tenant_name UNIQUE (tenant_id, name)` — the
  per-tenant unique name the API's 409 relies on (0009 lacked it). Local DB restored to the 0009 schema +
  the constraint; **`0014` down→up cycle clean**; full suite green.
- **Grant note:** migrations run as the `quantvista` admin role; CI's `Grant app role DML on migrated schema`
  step (`GRANT … ON ALL TABLES … TO quantvista_app` after `alembic upgrade`) covers new tables — so migrations
  carry no grant statement, consistent with every other migration.

### Completion Notes List

- **Screens are now reusable** — `POST/GET/DELETE /api/v1/screens`, tenant-isolated + tier-limited.
- **Migration `0014_saved_screens`** — tenant-scoped table (RLS `app_current_tenant()` policy, `FORCE`),
  `UNIQUE(tenant_id, name)`, `criteria jsonb`; mirrors `0011_backtests`. Downgrade drops it.
- **`analytics/saved_screens.py`** (100%): `create`/`list`/`count`/`delete` on the RLS session — the policy
  scopes every read/write, so no manual `WHERE tenant_id=`; the INSERT sets `tenant_id` for `WITH CHECK`;
  delete uses `RETURNING id` (→ 404 when RLS matches nothing, i.e. another tenant's id).
- **`POST /screens`** (100%): validates `criteria` via the **QV-038 allow-list** (`build_where`/`build_order`
  → 422 — never store an unrunnable screen), enforces the `saved_screens` tier limit (`count < limit`,
  NULL = unlimited → 403 `entitlement_exceeded`), and maps the `UNIQUE` violation → 409 `conflict`.
  `GET`/`DELETE` complete the CRUD; `ScreenNameTaken`/`ScreenNotFound` handlers → 409/404.
- **Running a screen = re-POST its `criteria` to `/screener`** (the criteria *is* a screener body) — no run
  endpoint, keeping the story at 3pts. `tenant_id`/`user_id` come from the verified `TenantContext`, never
  the body. **Not this story:** run endpoint, the screener/screens UI (QV-040), sharing/folders.

### File List

**New (backend/)**
- `src/quantvista/db/migrations/versions/0014_saved_screen_unique_name.py` — **adds** `UNIQUE(tenant_id, name)` to the `saved_screens` table that **already exists from `0009`** (not a new table).
- `src/quantvista/analytics/saved_screens.py` · `src/quantvista/schemas/screens.py` · `src/quantvista/api/routes_screens.py`
- `tests/integration/test_api_screens.py`

**Modified (backend/)** — `src/quantvista/api/app.py` (register `screens_router`; `ScreenNameTaken`→409, `ScreenNotFound`→404 handlers).
**Modified (repo):** `_bmad-output/.../sprint-status.yaml` — QV-039 status; QV-038 → done (housekeeping).

### Change Log

- **2026-07-08 — QV-039 saved screens (entitlement-limited).** `POST/GET/DELETE /api/v1/screens` (`04` §3.4)
  over the tenant-scoped, RLS-isolated `saved_screens` table (**created in `0009`**; `0014` adds
  `UNIQUE(tenant_id, name)`) storing a validated screener `criteria`; create enforces the `saved_screens`
  tier limit (Free 3 / Pro 25 / Quant ∞ → 403 over cap),
  validates criteria via the QV-038 allow-list (→ 422), and rejects duplicate names (→ 409). Running a screen
  = re-POST its criteria to `/screener`. 325 tests green (5 new; new code 100%); ruff/mypy-strict/import-linter
  clean; migration up+down clean. QV-040 (screener + saved-screens UI) builds on this.

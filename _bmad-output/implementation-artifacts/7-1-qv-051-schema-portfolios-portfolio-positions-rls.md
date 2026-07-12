---
baseline_commit: 45f5407bb82fbd6b2798dd6972513ef445a8c848
---

Status: review

# Story 7.1: QV-051 — Schema: portfolios + portfolio_positions (RLS)

**Epic:** EPIC-PORT (Epic 7) · **Points:** 5 · **Depends:** QV-004 (Postgres/RLS scaffolding ✓), QV-007 (entitlements ✓ — for the limit check)

## Story

As a user, I want to store portfolios and their positions, so I can analyze my holdings — each tenant sees and mutates only its own, and the `portfolios` plan limit is enforced.

## Acceptance Criteria

1. **`portfolios` + `portfolio_positions` are tenant-scoped with RLS** — every row carries `tenant_id`; `ENABLE + FORCE ROW LEVEL SECURITY` + a `{table}_isolation` policy on `app_current_tenant()`. **(Already shipped in migration `0008` — this story does NOT add a migration; see the ⚠️ note below.)**
2. **Cross-tenant denial test passes** — the mandatory RLS gate: tenant A cannot see or modify tenant B's portfolios/positions, and an unbound session sees nothing. Mirrors `tests/integration/test_rls_isolation.py`.
3. **`portfolios` entitlement enforced (US-06)** — creating a portfolio past the plan limit (Free `1` / Pro `5` / Quant `∞`) raises `EntitlementExceeded` (the `portfolios` key, already seeded). This is the **enforcement logic in the service/repo layer** (a count-vs-limit check + test); the HTTP `POST /portfolios` surface + Idempotency-Key + weight-sum validation are **QV-052**, not here.
4. **Repository + domain seam** — a `portfolio/repositories.py` data-access layer on the RLS tenant session (create/list/get/delete portfolio, `count_portfolios`, position upsert/list/delete) + typed DTOs in `portfolio/models.py`, mirroring `alerts/repositories.py` / `analytics.saved_screens`. Money/weights are `Decimal`/`NUMERIC`, never `float`.
5. **Gates green** — ruff + `ruff format` + mypy + import-linter clean; pytest ≥ 80% coverage on new code; no cross-module table access (portfolio talks to its own tables only).

## Tasks / Subtasks

- [x] **Task 1 — Verify the pre-declared schema; do NOT write a migration** (AC: #1)
  - [x] Confirmed `0008_portfolio_risk.py` already creates `portfolios`, `portfolio_positions` (+ `optimization_runs`, `risk_snapshots`) with `tenant_id`, FKs, `updated_at` triggers, indexes, and `_enable_rls` (ENABLE+FORCE+`{table}_isolation`). **No migration written** (would fail CI `DuplicateTable`).
  - [x] DDL is comprehensive and meets the story's needs — no missing column; no new migration required.
- [x] **Task 2 — Portfolio repository layer** (AC: #4)
  - [x] `portfolio/repositories.py` on the RLS tenant session (raw `text()`, mirrors `alerts/repositories.py`): `create_portfolio`, `list_portfolios` (newest-first), `get_portfolio`, `delete_portfolio` (RETURNING→bool), `count_portfolios`; positions: `upsert_position` (ON CONFLICT `(portfolio_id, stock_id)`), `list_positions`, `delete_position`. RLS-implicit scoping; `INSERT`s set `tenant_id` for the `WITH CHECK`. Money → `Decimal`.
- [x] **Task 3 — DTOs + create-with-entitlement service** (AC: #3, #4)
  - [x] **Deviation (documented):** kept the alerts/saved_screens convention — repo returns typed **dict rows** (a `_portfolio_row`/`_position_row` mapper), so standalone dataclass DTOs would be unused ceremony (YAGNI); typed Pydantic response models arrive with the API in QV-052.
  - [x] `portfolio/services.py`: `enforce_portfolio_limit(current_count, limit)` — **pure** guard raising `EntitlementExceeded("portfolios")` when `limit is not None and count >= limit`. Reused by the QV-052 route as `enforce_portfolio_limit(count_portfolios(session), entitlements.limit(tenant_id, PORTFOLIO_LIMIT_KEY))` — the alerts-route pattern, kept pure so it's unit-testable without a DB and doesn't pre-build QV-052's HTTP create.
- [x] **Task 4 — RLS denial + entitlement tests** (AC: #2, #3)
  - [x] `tests/integration/test_rls_portfolios.py`: mirrors `test_rls_isolation.py` via `session_scope(tenant_id)` — each tenant sees only its own portfolio; B cannot SELECT/UPDATE/DELETE A's rows (`rowcount == 0`); unbound session sees none. Covers BOTH `portfolios` and `portfolio_positions`.
  - [x] `tests/test_portfolio_services.py`: unlimited (`None`) never raises; under limit ok; at/over the limit (1) raises `EntitlementExceeded` with `feature == "portfolios"`. Plus `tests/integration/test_portfolio_repository.py` for the full CRUD + upsert-updates-same-pair.
- [x] **Task 5 — Gates + reconcile** (AC: #5)
  - [x] ruff + `ruff format` clean, mypy clean (112 files), `lint-imports` 3/3 kept (portfolio→identity is higher→lower, legal), full suite **474 passed / 5 skipped**, portfolio coverage 98% (repos + services 100%). Reconcile QV-051 → done after merge.

## Dev Notes

### ⚠️ No migration — the schema is forward-declared in `0008`
`portfolios`, `portfolio_positions`, `optimization_runs`, `risk_snapshots` **already exist** in `0008_portfolio_risk.py`, fully RLS-protected. This story is the **code layer** (repo + DTOs + entitlement enforcement + RLS tests) on top of that schema — exactly how QV-047 built alerts on the pre-declared `0010` tables. Do **not** add DDL for these tables. [Source: `backend/src/quantvista/db/migrations/versions/0008_portfolio_risk.py`; `[[forward-declared-schema-migrations]]`]

### Two data domains — portfolios are TENANT data (RLS)
Per project-context rule #1/#2: `portfolios`/`portfolio_positions` carry `tenant_id` and MUST be RLS-enforced with a cross-tenant denial test (a required CI gate). The `0008` migration already applies `ENABLE + FORCE RLS` + `{table}_isolation`. Use `quantvista.core.db.session_scope(tenant_id)` (the **non-superuser app role**) in tests — a superuser/BYPASSRLS connection passes these falsely. [Source: `_bmad-output/project-context.md#Critical Implementation Rules`; `tests/integration/test_rls_isolation.py`]

### Patterns to mirror (do not reinvent)
- **Repository:** `backend/src/quantvista/alerts/repositories.py` (raw `text()` on the RLS session, RETURNING for delete→bool, ON CONFLICT upsert) and `analytics` saved_screens. RLS makes tenant filtering implicit.
- **Entitlement enforcement:** `EntitlementService.limit(tenant_id, key)` returns `int | None` (`None` = unlimited); raise `EntitlementExceeded(feature)` (mapped to `entitlement_exceeded` 402/403 in `api/app.py`). The `portfolios` key is seeded Free `1` / Pro `5` / Quant `NULL`. [Source: `backend/src/quantvista/db/seeds/seed_reference.sql` lines 34/53/74; `backend/src/quantvista/identity/entitlements.py`]
- **RLS test:** `tests/integration/test_rls_isolation.py` + its `two_tenants` conftest fixture (seed A/B rows, assert visibility + `rowcount==0` on cross-tenant UPDATE/DELETE).

### Existing module seam
`backend/src/quantvista/portfolio/` exists with `interfaces.py` (Protocols: `IPortfolioService.holdings`, `IOptimizer`, `IRiskEngine`) — `models.py`/`repositories.py`/`services.py` are empty placeholders to fill. Keep `IPortfolioService` satisfied. Money is `Decimal`; modern typing (`X | None`), `from __future__ import annotations`. [Source: `backend/src/quantvista/portfolio/interfaces.py`]

### Scope boundary (what is NOT this story)
- **QV-052** owns the HTTP API: `POST /portfolios` with `Idempotency-Key`, positions CRUD endpoints, weight-sum/`weight ∈ [0,1]` validation, request/response envelope schemas, and wiring the entitlement guard into the route. QV-051 stops at the repo + service seam + tests.
- `optimization_runs` / `risk_snapshots` tables exist in `0008` but belong to QV-054/QV-058 — no code for them here.

### References
- [Source: `plans/sprints/sprint-06-portfolio-i.md#QV-051`] — story + AC (RLS + cross-tenant denial + `max_portfolios` entitlement, US-06)
- [Source: `plans/03-data-architecture.md#§4.3`] — portfolio data model
- [Source: `backend/src/quantvista/db/migrations/versions/0008_portfolio_risk.py`] — the live DDL + RLS
- [Source: `backend/src/quantvista/db/seeds/seed_reference.sql`] — `portfolios` entitlement per plan
- [Source: `tests/integration/test_rls_isolation.py`] — the RLS denial-gate pattern
- [Source: `backend/src/quantvista/alerts/repositories.py`] — the tenant-session repository pattern

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- RED: new tests failed to import (`count_portfolios` etc. absent) → GREEN after implementing repo + guard. 11 new tests pass.
- Gates: ruff + format clean; mypy clean (112 files); `lint-imports` 3/3 kept; full suite **474 passed / 5 skipped**; portfolio coverage 98% (repositories.py + services.py 100%; only the empty `models.py` placeholder line uncovered).

### Completion Notes List

- **No migration — schema forward-declared in `0008`.** Like QV-047 on `0010`, this story is the code layer on the pre-existing DDL (`portfolios`, `portfolio_positions`, both RLS-protected). Avoided the `DuplicateTable` trap (`[[forward-declared-schema-migrations]]`).
- **Entitlement key is `portfolios`** (Free 1 / Pro 5 / Quant ∞), already seeded in `seed_reference.sql` — NOT "max_portfolios" (the sprint plan's informal name). The `EntitlementExceeded` guard raises this key.
- **Enforcement kept pure + in the portfolio context.** `enforce_portfolio_limit(current_count, limit)` is a pure guard (unit-testable, no DB), reused by the QV-052 route which supplies `count_portfolios(session)` + `EntitlementService.limit(...)` — the alerts-route pattern. `portfolio` importing `identity` is DAG-legal (portfolio is a higher layer).
- **Repo returns dict rows** (not dataclass DTOs) to match the alerts/saved_screens convention; typed API models are a QV-052 concern.
- **RLS gate:** `test_rls_portfolios.py` proves cross-tenant denial on the non-superuser app role for both tables (the mandatory CI gate).
- **Scope held:** no HTTP API, no `optimization_runs`/`risk_snapshots` code (QV-052 / QV-054 / QV-058).

### File List

- Backend (impl): `src/quantvista/portfolio/repositories.py` (new — was placeholder), `src/quantvista/portfolio/services.py` (new — was placeholder)
- Backend (tests): `tests/test_portfolio_services.py` (new), `tests/integration/test_portfolio_repository.py` (new), `tests/integration/test_rls_portfolios.py` (new)

## Change Log

- QV-051 story drafted (ready-for-dev): code-layer foundation on the pre-declared `0008` portfolio schema.
- QV-051 implemented (review): `portfolio.repositories` (portfolios + positions CRUD on the RLS tenant session, money as `Decimal`) + `portfolio.services.enforce_portfolio_limit` (pure `portfolios` entitlement guard) + RLS cross-tenant denial tests (portfolios & positions) + repo/entitlement unit+integration tests. No migration (schema in `0008`). Gates green (474 passed / 5 skipped, coverage 98%).

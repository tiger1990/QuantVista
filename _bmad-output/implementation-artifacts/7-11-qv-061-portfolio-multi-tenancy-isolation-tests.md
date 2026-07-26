---
baseline_commit: 49664f39826c9a89417902215a3bbecdc8af9ce1
---

# Story 7.11: QV-061 — Portfolio multi-tenancy isolation tests

Status: review

**Epic:** EPIC-PORT (Epic 7) · **Points:** 3 · **Depends:** QV-051 (portfolios/positions + RLS), QV-058 (risk), and by extension QV-055 (optimize) + QV-059 (rebalance)

> **Type:** `[SEC]` — **test-only** story. Isolation is already enforced (Postgres RLS on all four portfolio tables + the `get_portfolio → 404` guard). This story is the **proof / regression guard**: prove a tenant can never see or mutate another tenant's portfolio, positions, risk snapshots, or optimize/rebalance results — for the WHOLE portfolio surface, especially the endpoints added after QV-051 (`/risk`, `/rebalance`, `/optimize`) whose existing "404" tests only use an *unknown* UUID, not a *foreign* tenant's real portfolio. No production code change expected.

## Story

As security, I want proof portfolios never leak across tenants, so isolation holds under the portfolio features.

## Acceptance Criteria

1. **API cross-tenant denial with a REAL foreign portfolio** — with two registered tenants A and B, where A owns a real portfolio (with positions + seeded prices), tenant B receives **404 `not_found`** (never 200/403/500, never A's data) on every portfolio-scoped endpoint targeting A's `portfolio_id`:
   - `GET /portfolios/{A}` , `DELETE /portfolios/{A}`
   - `PUT /portfolios/{A}/positions/{stock}` (write attempt) , `GET /portfolios/{A}/positions` , `DELETE /portfolios/{A}/positions/{stock}`
   - `GET /portfolios/{A}/risk`
   - `POST /portfolios/{A}/rebalance`
   - `POST /portfolios/{A}/optimize`
   The distinction from the existing tests matters: today `/risk`, `/rebalance`, `/optimize` only assert 404 for an **unknown** `uuid4()`; this asserts 404 for a **real portfolio owned by another tenant** (RLS-invisible), and that A's portfolio/positions are unchanged after B's write/delete attempts.
   [Source: `07` §3; `plans/07` §3; QV-051 RLS]

2. **A's data does not leak in B's list views** — `GET /portfolios` as B returns only B's portfolios (A's absent); after B's failed mutation attempts, A's `GET /portfolios/{A}` + `/positions` are byte-for-byte unchanged.
   [Source: `07` §3]

3. **Repository / RLS-level denial (defense-in-depth below the API)** — on the non-superuser app session (`session_scope(tenant_B)`), the RLS policy makes A's rows invisible/unwritable:
   - reads of A's `portfolios` / `portfolio_positions` / `risk_snapshots` return nothing under B's binding
   - an attempt to `INSERT`/`UPDATE` a row carrying A's `tenant_id` under B's binding fails the `WITH CHECK` (RLS violation), i.e. a logic bug can't cross tenants even if the API guard were bypassed
   [Source: `0008_portfolio_risk` RLS policies; project rule #2]

4. **Risk-snapshot isolation** — after A computes risk (a `risk_snapshots` row is persisted for A), B cannot read it via `/risk` (404) nor via a B-bound repo session; the snapshot stays A's.
   [Source: QV-058 `risk_snapshots` (RLS); `07` §3]

5. **CI-gated** — all new tests are `@pytest.mark.integration` so they run in the required **`backend-rls`** CI job (real PostgreSQL + the non-superuser `quantvista_app` role); a failing isolation test blocks merge. No test is skippable in that job.
   [Source: `.github/workflows/ci.yml` `backend-rls`; project rule #2 "required CI gate"]

---

## Dev Notes

### Type & intent

This is a **security regression-guard** story: the isolation mechanism (RLS + the `get_portfolio → PortfolioNotFound → 404` pattern) already exists and works (proven live in QV-060 verification). QV-061 adds the **missing proofs** so a future refactor that weakens isolation fails CI. Expect **no `src/` changes** — only new/expanded tests. If a test reveals a real leak, THAT becomes a fix (but none is expected).

### What already exists (do NOT duplicate — extend the gaps)

- `tests/integration/test_api_portfolios.py::test_cross_tenant_isolation_is_404` — already covers **portfolio GET/DELETE + positions** across tenants (A vs B via `token_a`/`token_b` from its `api` fixture). **Gap:** it does NOT cover `/risk`, `/rebalance`, `/optimize`, nor position **write** (PUT) into a foreign portfolio, nor risk-snapshot isolation.
- `test_api_risk.py`, `test_api_optimize.py`, `test_api_rebalance.py` — their "cross-tenant/unknown → 404" tests use a bare `uuid4()` (**unknown**, not **foreign**). Add real-foreign-tenant variants.
- `test_portfolio_repository.py` — single-tenant CRUD on `session_scope(tenant)`. **Gap:** no cross-tenant RLS denial (B can't see/write A's rows).

### Fixtures & patterns to reuse (match these exactly)

- **API two-tenant pattern** — `test_api_portfolios.py`'s `api` fixture registers two users and yields `(client, token_a, token_b, stock)`; helper `_h(token)` builds the auth header, `_create(client, token, **over)` posts a portfolio. **Reuse this shape.** To also get **prices** (needed for `/risk` + `/rebalance` to reach the compute path rather than 422), mirror `test_api_risk.py`'s fixture which seeds a market + priced stocks (`daily_prices`), or seed prices in the setup. A's portfolio must have **positions with shares + a target** and **priced stocks** so `/risk` and `/rebalance` return 200 for A (then assert B gets 404).
- **Repo/RLS pattern** — `test_portfolio_repository.py` uses `session_scope(tenant_id)` (the non-superuser role, RLS active) + `admin_engine` (superuser, bypasses RLS) for seeding/teardown. For cross-tenant: seed A's rows via `admin_engine` (or a `session_scope(A)` write), then assert `session_scope(B)` reads see nothing and a B-bound write of an A-`tenant_id` row raises (RLS `WITH CHECK`). The `two_tenants` fixture in `tests/conftest.py` (seeds tenants A+B + a shared user) is a good base for repo-level tests.
- **Marker** — every test: `pytestmark = pytest.mark.integration` (module-level, as the other integration files do) so it runs in `backend-rls` and auto-skips when no DB is reachable (the `conftest.pytest_collection_modifyitems` guard).
- **Teardown** — delete the test tenants (cascades portfolios/positions/risk_snapshots via `ON DELETE CASCADE`) + users + seeded stocks/markets, exactly like the existing fixtures' teardown blocks.

### Endpoints under test (all in `api/routes_portfolios.py`)

All portfolio-scoped handlers open `get_tenant_session` (binds `SET LOCAL app.tenant_id`) and call `get_portfolio(session, portfolio_id)` first → `PortfolioNotFound → 404` when RLS hides the row. So a foreign portfolio is **indistinguishable from a non-existent one** (correct — no existence oracle). Endpoints: `GET/DELETE /portfolios/{id}`, `PUT/GET/DELETE /portfolios/{id}/positions[/{stock}]`, `GET /portfolios/{id}/risk`, `POST /portfolios/{id}/rebalance`, `POST /portfolios/{id}/optimize`. (`/optimize` is entitlement-gated — B's token needs the plan OR the 404 must fire **before** the entitlement check; verify the handler order so B gets **404, not 403** — a 403 would leak that the portfolio exists. Check `routes_portfolios.py:247` handler: it should resolve the portfolio 404 first. If it 403s first, that's a real finding to fix.)

### RLS specifics (from `0008_portfolio_risk.py`)

Every portfolio table: `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + policy `{table}_isolation USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())`. `FORCE` matters — it applies RLS even to the table owner. The app connects as the non-superuser `quantvista_app` role (no `BYPASSRLS`). A B-bound `INSERT ... tenant_id = A` violates `WITH CHECK` → `psycopg` raises (expect an exception, assert it).

### Previous-story intelligence (QV-060)

- Integration tests live in `backend/tests/integration/`, marked `pytest.mark.integration`, and run in the `backend-rls` CI job (real PG + `quantvista_app` role). The DB-free unit job skips them.
- `/risk` + `/rebalance` need **positions with shares + a target + priced stocks** to reach 200 (else 422 "no positions"/"no price data"). Seed prices (mirror `test_api_risk.py`).
- The QV-060 live verification already exercised cross-tenant `404` informally; QV-061 makes it a permanent CI gate.
- Money/weights are Decimal-as-string; register uses `POST /api/v1/auth/register` (rate limiting is OFF by default in tests).

### Git intelligence (recent)

`49664f3` QV-060 (risk/rebalance UI + COALESCE upsert + drawdown_series) · `66667dd` QV-079 security hardening · `a25f4e3` QV-059 rebalance · `300b5f6` QV-058 RiskEngine. The portfolio surface + RLS are all in `master`. This story only adds tests.

### Project context reference

See `_bmad-output/project-context.md` rule #2 ("Tenant isolation is enforced by Postgres RLS, not app code" — "**Every tenant-scoped feature needs a cross-tenant-access-denial test — this is a required CI gate, not optional**") and rule #1 (two data domains). Related: [[ci-required-status-checks]] (the `backend-rls` gate), and the RLS scaffolding from QV-004.

---

## Tasks / Subtasks

### Task 1: API cross-tenant denial for the new endpoints (real foreign portfolio)
- [x] 1a. In `tests/integration/` add a two-tenant fixture (or extend an existing one) that gives `token_a`, `token_b`, a **priced** market/stocks, and A owning a portfolio with **positions (shares + target)** — so A's `/risk` + `/rebalance` return 200
- [x] 1b. Assert B → **404** on A's `GET/DELETE /portfolios/{A}`, `GET/PUT/DELETE /portfolios/{A}/positions[/{stock}]`, `GET /portfolios/{A}/risk`, `POST /portfolios/{A}/rebalance`, `POST /portfolios/{A}/optimize`
- [x] 1c. Assert `POST /portfolios/{A}/optimize` as B returns **404 (not 403)** — the portfolio-not-found guard must fire before the entitlement gate (verify handler order; if it 403s, fix the order in `routes_portfolios.py` so existence isn't leaked)
- [x] 1d. Assert A's portfolio + positions are **unchanged** after B's write/delete attempts; `GET /portfolios` as B excludes A's portfolio

### Task 2: Repository / RLS-level denial
- [x] 2a. Seed A's `portfolios` + `portfolio_positions` (+ a `risk_snapshots` row) via admin/`session_scope(A)`; assert `session_scope(B)` reads see **none** of them
- [x] 2b. Assert a B-bound write (`create_portfolio`/`upsert_position`/`upsert_risk_snapshot`) carrying A's `tenant_id` raises (RLS `WITH CHECK` violation) — a logic bug can't cross tenants
- [x] 2c. Prefer reusing repo functions (`portfolio.repositories`) over raw SQL where practical, to exercise the real code path

### Task 3: Risk-snapshot isolation
- [x] 3a. A computes risk (`GET /portfolios/{A}/risk` → persists a snapshot); assert B cannot read it via `/risk` (404) nor a B-bound repo read; the snapshot row remains A's (verify via `admin_engine`)

### Task 4: Gates + sprint status
- [x] 4a. All new tests `@pytest.mark.integration`; confirm they run under `pytest -m integration` (the `backend-rls` job) and auto-skip DB-free
- [x] 4b. Full-tree backend gates: `ruff check . && ruff format --check . && mypy && lint-imports && bandit -c pyproject.toml -r src/ -ll -q && pip-audit --skip-editable && pytest` — green (no regressions)
- [x] 4c. Update `sprint-status.yaml` → review; fill Dev Agent Record

---

## Dev Agent Record

### Debug Log

- **AC 1c confirmed a real finding (RED→GREEN):** `/optimize` ran `entitlements.check` **before** `get_portfolio → 404`, so a Free-tier foreign tenant got **403** on someone else's portfolio instead of 404 (`/risk` + `/rebalance` already resolve 404 first). The isolation test asserted 404 → failed at 403 → **fixed** by moving the ownership check above the entitlement gate in `optimize_portfolio_endpoint`. Existing `test_optimize_free_tier_forbidden` still 403s (own portfolio is found first, then the entitlement check fires) — reorder verified safe.
- `list_portfolios(session)` is RLS-scoped (no `tenant_id` arg) — fixed the test call.
- RLS `WITH CHECK` violation surfaces as `sqlalchemy.exc.DBAPIError` (SQLSTATE 42501) — used that specific type (satisfies ruff B017, not a blind `Exception`).
- `_tenant_id` wraps `scalar_one()` in `UUID(str(...))` for mypy (`scalar_one()` returns `Any`).

### Completion Notes List

- **Test-only story + one small production fix.** Added `tests/integration/test_portfolio_tenant_isolation.py` (6 tests) proving cross-tenant isolation across the full portfolio surface, and reordered the `/optimize` ownership/entitlement checks (the only `src/` change, driven by AC 1c).
- **Task 1 (API):** with two tenants A/B (A owns a priced portfolio with positions), B gets **404** (`not_found`) on A's `GET/DELETE /portfolios/{A}`, `GET/PUT/DELETE /positions`, `GET /risk`, `POST /rebalance`, `POST /optimize` — a **real foreign portfolio**, closing the gap where those endpoints only tested an unknown `uuid4()`. Sanity test proves A (owner) reaches 200 (risk/rebalance) / 403 (optimize, Free) so the 404s are isolation, not a broken portfolio. B's list excludes A; A's data is unchanged after B's failed writes/deletes.
- **Task 2 (RLS):** on `session_scope(tenant_B)` (non-superuser role) A's `portfolios`/`portfolio_positions` are invisible (`count == 0`, `list_portfolios == []`); a B-bound write carrying A's `tenant_id` (`create_portfolio`, `upsert_position`) raises `DBAPIError` (WITH CHECK) — a logic bug cannot cross tenants. A's own binding still sees A's rows.
- **Task 3:** A computes risk (persists a `risk_snapshots` row); B cannot read it via `/risk` (404) nor a B-bound repo session; the row stays A's (verified via `admin_engine`).
- **CI:** all `@pytest.mark.integration` → run in the required `backend-rls` job (real Postgres + `quantvista_app` role); auto-skip DB-free. Full suite **668 passed / 5 skipped**; ruff/format/mypy(252)/lint-imports(3/3)/bandit/pip-audit green. No migration.
- **Closes Epic 7** (EPIC-PORT) — last story.

### File List

**New**
- `backend/tests/integration/test_portfolio_tenant_isolation.py` — 6 cross-tenant isolation tests (API + RLS repo + risk-snapshot)

**Modified**
- `backend/src/quantvista/api/routes_portfolios.py` — `/optimize`: resolve `get_portfolio → 404` before the entitlement gate (no 403 existence leak; consistent with `/risk` + `/rebalance`)

### Change Log

- **2026-07-26 — QV-061 portfolio multi-tenancy isolation tests.** Added an integration suite proving no cross-tenant leak across the portfolio surface (API 404 for a real foreign portfolio incl. `/risk` `/rebalance` `/optimize`; RLS repo-level denial incl. `WITH CHECK` write refusal; risk-snapshot isolation). Fixed `/optimize` to check ownership (404) before entitlement (403) so existence isn't leaked. 668 passed/5 skipped; CI-gated in `backend-rls`. No migration. Closes Epic 7.

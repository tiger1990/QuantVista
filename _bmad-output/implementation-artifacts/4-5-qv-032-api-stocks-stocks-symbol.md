---
baseline_commit: 81b87a0c6de8e895d57085e075bf407413467fbf
---

# Story 4.5: QV-032 — API: /stocks, /stocks/{symbol}

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user/client**,
I want **to list and inspect stocks over HTTP**,
so that **I can browse the universe and see a stock's master data + latest snapshot**.

> Canonical ID **QV-032** · Epic 4 (EPIC-INTEL) · `[BE]` · 5pts · Sprint 03 · depends: **QV-031 ✅** (cache), **QV-007 ✅** (auth/tenant)
> Authoritative: `04` §3.2 (`GET /stocks`, `GET /stocks/{symbol}`; cursor pagination `?limit&cursor` → `meta.next_cursor`; disclaimer header + field on score-bearing responses). First read-API surface for Epic 4.

## What exists (reuse, don't rebuild)

- **`Envelope[T]`** (`schemas/envelope.py`) — `{success, data, error, meta}`, `Envelope.ok(data, meta=…)`, `meta.next_cursor` for pagination, `ERROR_STATUS` code→HTTP map. **Reuse.**
- **Auth deps** (`api/deps.py`) — `get_current_principal` (401 if unauth), `get_tenant_session` (RLS), `require_entitlement(feature)`. **Reuse `get_current_principal`.**
- **`privileged_session_scope()`** (`core/db.py`) — global/reference reads, no RLS. `stocks`/`scores`/`daily_prices`/`fundamentals` are **global** → read via this, **not** the tenant session.
- **`ICache`/`get_cache()`** (QV-031), `rankings_for` (QV-029). **No migration.**

## Locked decisions

- **`GET /stocks` — cursor pagination keyed on `symbol` (v1).** Filters: `market` (default `NSE`), `sector`, `market_cap_bucket`. **Keyset** on the stable unique `symbol` (`WHERE symbol > :cursor ORDER BY symbol LIMIT n+1`; fetch one extra to compute `next_cursor`); the cursor is an **opaque base64** of the last symbol. `sort=symbol` asc/desc. **Score-sorted rankings are QV-033's `/rankings`** — `/stocks` is universe browse, not a leaderboard.
- **`GET /stocks/{symbol}` — master + latest snapshot.** Master (`symbol, company_name, sector, industry, market_cap_bucket, market, is_active`) + latest snapshot: latest `daily_prices` (close/date), latest `scores` (composite + 5 sub-scores + coverage + versions), key latest `fundamentals` (pe/pb/roe/roce/debt_equity). Cached under **`stock:{id}:detail`** with the TTL backstop (QV-031's noted addition). 404 (`not_found`) for an unknown symbol.
- **Global reads via a new `get_global_session` dep** (yields `privileged_session_scope()`) — stocks/scores/prices/fundamentals carry no `tenant_id`, so RLS must not apply. **Read-models in `analytics/repositories.py`** (`list_stocks`, `stock_detail`) — analytics is the top read layer; joins reference + score/price/fundamentals via SQL.
- **Auth-required, all tiers.** Both endpoints require an authenticated principal (`get_current_principal`); browsing the universe is a basic authenticated read (no entitlement gate). Per-feature score gating lands with QV-033's scores API.
- **Disclaimer on score-bearing responses** (`04` §3.2 / `07`). Both endpoints carry scores → set the response header **`X-QuantVista-Disclaimer: research-only; not investment advice`** + a **`disclaimer`** string in `meta` ("Research signal, not investment advice."). A small helper applies both.
- **Pydantic schemas** in `schemas/stocks.py` (`StockListItem`, `StockDetail`, `LatestSnapshot`). Routes in `api/routes_stocks.py`, `response_model=None`, returning `Envelope[...]`. Registered on the app. **No migration.**

## Acceptance Criteria

1. **`GET /api/v1/stocks`** — authenticated; filters `market`/`sector`/`market_cap_bucket`; `limit` (default 50, capped e.g. 100) + opaque `cursor`; returns `Envelope.ok([StockListItem…], meta={next_cursor, disclaimer})`; **keyset-correct** (stable order, no dup/skip across pages; `next_cursor=null` on the last page). Each item: symbol, name, sector, market_cap_bucket, market, latest composite_score (nullable). Disclaimer header set.
2. **`GET /api/v1/stocks/{symbol}`** — authenticated; returns `Envelope.ok(StockDetail)` = master + latest snapshot (price, scores+coverage+versions, key fundamentals) + `disclaimer`; **cached** under `stock:{id}:detail` (TTL); 404 `not_found` for an unknown symbol. Disclaimer header set.
3. **Read-models.** `list_stocks(session, *, market, sector, market_cap_bucket, limit, cursor)` (keyset) + `stock_detail(session, symbol)` (master + latest price/score/fundamentals) in `analytics/repositories.py`, on the global session.
4. **Envelope + errors.** Success uses `Envelope.ok`; unknown symbol → `Envelope.fail("not_found", …)` at 404 (via `ERROR_STATUS`); unauth → 401 (existing auth dep). Cursor pagination in `meta`.
5. **Boundaries.** Routes in `api` (composition root); read-models in `analytics`; schemas in `schemas` (Pydantic leaf). Global tables → `get_global_session` (no RLS). `lint-imports` green. **No migration.**
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80 % coverage. **Unit:** cursor encode/decode; disclaimer helper; list schema mapping. **Integration** (real Postgres via `TestClient`, seeded stocks + a score): `GET /stocks` paginates (page 1 `next_cursor` set, page 2 resumes, no overlap) + filters by sector; `GET /stocks/{symbol}` returns master+snapshot + disclaimer header + is cache-served on the 2nd call; unknown symbol → 404; unauth → 401.

## Tasks / Subtasks

- [x] **Task 1 — schemas + cursor + disclaimer helpers** (AC: #1, #2, #4)
  - [x] `schemas/stocks.py`: `StockListItem`, `LatestSnapshot`, `StockDetail` (Pydantic). `api/pagination.py` (or in routes): opaque base64 `encode_cursor`/`decode_cursor`. `api/disclaimer.py` (or helper): the header const + `DISCLAIMER` string + `apply_disclaimer(response, meta)`.
- [x] **Task 2 — read-models** (AC: #3)
  - [x] `analytics/repositories.py`: `list_stocks(...)` (filter + keyset on symbol, `limit+1`, returns rows + derived `next_cursor`); `stock_detail(session, symbol)` (LEFT JOIN latest price/score/fundamentals; `None` if symbol unknown).
- [x] **Task 3 — global session dep + routes** (AC: #1, #2, #5)
  - [x] `api/deps.py`: `get_global_session` → `privileged_session_scope()`; `GlobalSessionDep`. `api/routes_stocks.py`: `GET /stocks` + `GET /stocks/{symbol}` (auth-required, envelope, disclaimer, cursor, `stock:{id}:detail` cache-aside via `get_cache()`, 404). Register in `app.py`.
- [x] **Task 4 — tests + gates + reconcile** (AC: #6)
  - [x] `tests/test_pagination.py` (cursor round-trip) + `tests/integration/test_api_stocks.py` (TestClient + real PG + auth: list/paginate/filter, detail + cache + disclaimer header, 404, 401). Run gates; reconcile QV-031 → done (already applied).

## Dev Notes

### Cursor pagination (keyset, opaque)
```
GET /stocks?limit=50 → rows ORDER BY symbol LIMIT 51; if 51 returned, drop the 51st,
   next_cursor = b64(rows[50].symbol); else next_cursor = null.
GET /stocks?cursor=<b64> → symbol > decode(cursor), same order/limit.
```
Keyset (not OFFSET) → stable under inserts, O(1) deep pages. `symbol` is unique → no tie-breaker needed.

### Reuse map
- `Envelope.ok/fail` + `ERROR_STATUS` (`schemas/envelope.py`); `get_current_principal` + the app/router wiring (`api/routes.py`, `api/app.py` `include_router`) — QV-006.
- `privileged_session_scope` (`core/db.py`) for global reads; `get_cache()` (QV-031) for the detail cache; `scores`/`stocks`/`markets`/`daily_prices`/`fundamentals` tables.
- FastAPI `TestClient` + the auth flow (register/login → bearer) for integration — mirror `test_api_auth.py` if present.

### Boundaries & gates
- `api` (composition root) imports `analytics` read-models + `schemas` + `identity` (auth) + `core`. `analytics/repositories.py` reads global tables via SQL (no new cross-context code import). `schemas/stocks.py` = Pydantic leaf. `lint-imports` 3/3. Coverage ≥ 80 % on read-models + routes + cursor. **Not this story:** `/stocks/{symbol}/prices` + `/scores`/`/decomposition`/`/rankings` (QV-033); `/stocks/{symbol}/news` (Epic 5); precise event-invalidation of `stock:{id}:detail` (TTL backstop for now); the frontend (QV-035).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Verified against local **PostgreSQL 18.4** + native Redis (via `create_app()` `TestClient`).
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (148 files) ·
  `lint-imports` 3 kept/0 broken (`api` composition root; `analytics` read-models; `schemas` Pydantic leaf) ·
  `pytest` → **300 passed, 4 skipped**. Coverage 95 %; new: `api/routes_stocks.py` **100 %**,
  `api/pagination.py` **100 %**, `analytics/repositories.py` 91 %, `api/deps.py` 94 %.
- **Fix:** psycopg3 couldn't infer the type of the `NULL` filter params (`:sector IS NULL`) → wrapped in
  `CAST(:param AS text)`, which pins the type. The broad `ValueError` handler was replaced with a specific
  `InvalidCursor` exception (a blanket `ValueError`→422 would mask unrelated bugs).

### Completion Notes List

- **First read-API surface for Epic 4** — `GET /stocks` + `GET /stocks/{symbol}`, authenticated, on the
  standard `Envelope`. The intelligence engine is now reachable over HTTP.
- **`GET /stocks`** (`routes_stocks.py`, 100 %): filters `market`/`sector`/`market_cap_bucket`, **keyset
  cursor pagination on `symbol`** (opaque base64, fetch `limit+1` to derive `meta.next_cursor`) — proven
  stable across pages with no overlap and `next_cursor=null` on the last page. Each item carries the latest
  composite_score (nullable). Score-sorted rankings stay QV-033's `/rankings`.
- **`GET /stocks/{symbol}`** (100 %): master + latest snapshot (latest price, latest scores + coverage +
  versions, latest open-version fundamentals via `LEFT JOIN LATERAL`), cached under `stock:{symbol}:detail`
  (TTL backstop, QV-031's `get_cache()`); 404 `not_found` for an unknown symbol.
- **Read-models** (`analytics/repositories.list_stocks`/`stock_detail`) on a **new `get_global_session`**
  dep (`privileged_session_scope`, no RLS — stocks/scores/prices/fundamentals are global). **Disclaimer**
  header `X-QuantVista-Disclaimer` + `meta.disclaimer` on every score-bearing response (`04` §3.2 / `07`).
- **Boundaries:** routes in `api`; read-models in `analytics`; Pydantic DTOs in `schemas` (leaf). `not_found`
  added to `ERROR_STATUS`; `StockNotFound`/`InvalidCursor` → envelope handlers. **No migration; no
  security-reviewer** beyond the existing auth dep (read-only reference/score data; auth enforced).
  **Not this story:** `/stocks/{symbol}/prices` + `/scores`/`/decomposition`/`/rankings` (QV-033); news
  (Epic 5); precise `stock:detail` event-invalidation (TTL for now); the frontend (QV-035).

### File List

**New**
- `backend/src/quantvista/schemas/stocks.py` — `StockListItem`, `LatestSnapshot`, `StockDetail` DTOs.
- `backend/src/quantvista/api/pagination.py` — opaque keyset cursor (`encode`/`decode`, `InvalidCursor`).
- `backend/src/quantvista/api/routes_stocks.py` — `GET /stocks` + `GET /stocks/{symbol}` + disclaimer + `StockNotFound`.
- `backend/tests/test_pagination.py` — cursor round-trip (unit).
- `backend/tests/integration/test_api_stocks.py` — list/paginate/filter/detail/404/401 (TestClient + real PG + auth).

**Modified**
- `backend/src/quantvista/analytics/repositories.py` — `list_stocks` + `stock_detail` read-models.
- `backend/src/quantvista/api/deps.py` — `get_global_session` + `GlobalSessionDep`.
- `backend/src/quantvista/api/app.py` — register `stocks_router` + `StockNotFound`/`InvalidCursor` handlers.
- `backend/src/quantvista/schemas/envelope.py` — `not_found: 404` in `ERROR_STATUS`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-032 status; QV-031 → done (housekeeping).

### Change Log

- **2026-07-08 — QV-032 API: /stocks, /stocks/{symbol}.** The first Epic-4 read endpoints: an authenticated,
  cursor-paginated (keyset on `symbol`) universe browse + a per-symbol master+snapshot (latest price/scores/
  fundamentals) cached under `stock:{symbol}:detail`. Standard `Envelope`, disclaimer header + `meta.disclaimer`
  on score-bearing responses, 404/401 via envelope handlers. Read-models in `analytics` over a new global
  (no-RLS) session dep; Pydantic DTOs in `schemas`. No migration. 300 tests green, coverage 95 %
  (routes + cursor 100 %); ruff/mypy-strict/import-linter clean. QV-033 (scores/rankings API) builds on this.

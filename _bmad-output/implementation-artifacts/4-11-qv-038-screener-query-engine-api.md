---
baseline_commit: 36af9d6a52279c647022f79229a06be6cc25fe0a
---

# Story 4.11: QV-038 — Screener query engine + API

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **to filter/sort the universe by any factor/fundamental**,
so that **I find candidates fast**.

> Canonical ID **QV-038** · Epic 4 (EPIC-INTEL) · `[BE]` · 8pts · depends: **QV-033 ✅** (scores/stocks reads)
> Authoritative: `04` §3.4 (`POST /screener` — `filters[]` + `sort` + `limit` → rows + `meta.count`) · **US-01** (< 1s full-universe). **Security-sensitive** (user input → SQL): the allow-list is the defence.

## What exists (reuse)

- **Row-per-stock assembly** — `_STOCK_DETAIL_SQL` (`analytics/repositories.py`) already LATERAL-joins the latest score + latest open fundamentals per stock (`composite_score`, 5 sub-scores, `coverage`, `pe/pb/roe/roce/debt_equity`, `sector`, `market_cap_bucket`, `market`). The screener generalises this over the universe with a WHERE/ORDER/LIMIT.
- **Envelope + auth** — `Envelope`, `get_current_principal`, `get_global_session`, `ERROR_STATUS` (`validation_error` 422), the disclaimer helper — QV-032/033. `encode_cursor`/`decode_cursor` + `InvalidCursor` — `api/pagination.py`.

## Locked decisions

- **Allow-list DSL = the injection defence** (`analytics/screener.py`): an enumerated `FIELDS` map (`name → trusted SQL column expr`) + an `OPERATORS` map (`gte→">="`, `lte→"<="`, `gt→">"`, `lt→"<"`, `eq→"="`). A filter `{field, op, value}` is validated: **field ∈ FIELDS, op ∈ OPERATORS, value type matches the field's kind** (numeric vs categorical). The WHERE is built from the **allow-list-mapped column** + the operator token + a **bound parameter** for the value — **user strings never enter SQL text.** Unknown field/op or bad value → raise → **422 `validation_error`**.
- **Sort allow-list:** `sort = "-composite_score"` / `"momentum_score"` — the field must be in `FIELDS`; leading `-` = DESC (default), else ASC. Default `-composite_score`. NULLS LAST always (unscored stocks sink).
- **`POST /api/v1/screener`** (auth): Pydantic body `{ universe?="NIFTY200", market?="NSE", filters: [{field, op, value}], sort?, limit?=100 (1..500), cursor? }` → validate via the allow-list → assembled query → `Envelope[list[ScreenerRow]]` with `meta = {count, next_cursor, disclaimer}`. `count` = total matches (`COUNT(*) OVER ()`).
- **Pagination = opaque offset-backed cursor** (base64 of the next offset) + `meta.count`. Pragmatic + correct for the **bounded daily-snapshot** universe (`/stocks`' keyset is by *fixed* symbol; the screener sorts *arbitrarily*, where keyset-on-sort with NULLS LAST is far fiddlier). **Keyset-on-sort is a documented scale follow-up.**
- **Auth-only, not entitlement-gated** — result quotas are **QV-039**'s (saved screens) concern; here, bounded by `limit`. Global read via `get_global_session`.
- **Perf:** one assembled query over the bounded universe (LATERAL latest-score/fundamentals) → < 1s for ~200 stocks (US-01). A **materialized/cached projection is a deferred optimization** (note in `pending-verifications`), not built now — "cached projections where possible" is satisfied for the dev universe by the direct query.
- **Honest dev-data caveat:** fundamentals filters (`roe`,`pe`,…) match little until licensed data (QV-072); score/coverage filters work on the seeded scored universe today. Filters on null fields simply don't match (NULLS excluded by `>=` etc.).
- **Placement:** DSL in `analytics/screener.py`; the query in `analytics/repositories.py` (`screen(...)`); DTOs in `schemas/screener.py`; route in `api/routes_screener.py`. **Migration:** none (reads existing tables).

## Acceptance Criteria

1. **Allow-list validation (no injection).** `POST /screener` accepts only fields/operators on the allow-list; an unknown field, unknown op, or type-mismatched value → **422 `validation_error`** with a clear message. Values are always bound parameters (a test asserts an injection-style value is treated as data, not SQL).
2. **Filter + sort + paginate.** Multiple filters AND-combined; `sort` (whitelisted, `-` = desc, NULLS LAST); opaque cursor pagination; `meta.count` = total matches; `limit` bounded (1..500, default 100).
3. **Rows.** Each row: `symbol, company_name, sector, market_cap_bucket, market, composite_score, fundamental/momentum/quality/sentiment/risk, coverage, pe, pb, roe, roce, debt_equity` — nulls preserved. Disclaimer header + `meta.disclaimer`.
4. **Performance.** Full-universe query returns well under 1s on the seeded universe (documented); direct assembled query (materialized projection deferred).
5. **Boundaries.** DSL + query in `analytics`; DTOs in `schemas`; route in `api` (global session). `lint-imports` green. No migration.
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` (≥80% on the new code) green. **Unit:** the allow-list validator (accept/reject fields/ops/values; injection value bound as data; sort parsing). **Integration** (real PG + auth via TestClient): filter (`composite_score gte`), multi-filter AND, sort desc NULLS LAST, cursor page 2, `meta.count`, and a **422 on a non-allow-list field** + an **injection-string value returns 0 rows / no error** (proves parameterization).

## Tasks / Subtasks

- [x] **Task 1 — allow-list DSL** (AC: #1, #2)
  - [x] `analytics/screener.py`: `FIELDS` (name→column) + `OPERATORS` maps; `FilterSpec`/`SortSpec` validation → `(sql_fragment, params)` builder; `parse_sort`; a `ScreenerError` → 422. Pure + unit-tested (no DB).
- [x] **Task 2 — screen query** (AC: #2, #3, #4)
  - [x] `analytics/repositories.py`: `screen(session, *, market, filters_sql, params, order_sql, limit, offset) -> (rows, count)` — assembled LATERAL row-per-stock + built WHERE/ORDER + `COUNT(*) OVER ()` + LIMIT/OFFSET. `schemas/screener.py`: `ScreenerRow`, `ScreenRequest`, `FilterClause`.
- [x] **Task 3 — route** (AC: #1, #2, #3, #5)
  - [x] `api/routes_screener.py`: `POST /api/v1/screener` (auth) → validate via the DSL (→422) → `screen(...)` → `Envelope[list[ScreenerRow]]` + `meta{count, next_cursor, disclaimer}` + disclaimer header. Offset cursor via `encode/decode_cursor`. Register in `app.py`; `ScreenerError` handler → 422.
- [x] **Task 4 — tests + gates + reconcile** (AC: #6)
  - [x] `tests/test_screener_dsl.py` (unit) + `tests/integration/test_api_screener.py` (real PG + auth). Run gates. Note the cached-projection + keyset-on-sort follow-ups in `pending-verifications`. Reconcile QV-037 → done (already applied).

## Dev Notes

### Injection defence (the point of the story)
```
# SAFE: column from the allow-list, operator from the allow-list, value is a bound param
col = FIELDS[spec.field]          # KeyError → 422; never user text
op  = OPERATORS[spec.op]          # KeyError → 422
where.append(f"{col} {op} :p{i}") # col/op are trusted tokens
params[f"p{i}"] = spec.value      # value is DATA, bound — never interpolated
```
A filter like `{"field":"roe","op":"gte","value":"15; DROP TABLE stocks"}` fails value-type validation (roe is numeric) or, if forced through as a string on a categorical field, is bound as a literal → matches nothing, executes nothing. Test both.

### Fields (from the stock-detail assembly)
numeric: `composite_score, fundamental_score, momentum_score, quality_score, sentiment_score, risk_score, coverage, pe, pb, roe, roce, debt_equity`; categorical (`eq` only): `sector, market_cap_bucket`. Sort allow-list = the numeric set + `symbol`.

### Boundaries & perf
Assembled query mirrors `_STOCK_DETAIL_SQL` (LATERAL latest score + open fundamentals) but over the market's stocks with the built WHERE. `COUNT(*) OVER ()` gives `meta.count` in one pass. Bounded universe → < 1s. **Not this story:** saving screens (QV-039), the screener UI (QV-040), materialized projection, keyset-on-sort, portfolio/optimize (`04` §3.5). **Security-sensitive** — user input → SQL; the allow-list + bound params are the control (consider a security-reviewer pass on the DSL).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** `ruff` + `ruff format --check` clean · `mypy --strict` Success (159 files) · `lint-imports`
  3/3 · full `pytest` suite **320 passed / 4 skipped**. Coverage: `analytics/screener.py` **100%**,
  `schemas/screener.py` **100%**, `api/routes_screener.py` 94% (95% overall).
- **QV-038 tests:** 7 DSL unit + 5 integration (real PG + auth) = 12 passed — incl. **422 on a
  non-allow-list field** and **injection value → bound as data, 0 rows, no error**.
- Fixed test typing: `_post` returns `httpx.Response` (was `object`); dropped an unused `UUID` import.

### Completion Notes List

- **The universe is now queryable by any factor/fundamental** — `POST /api/v1/screener`, the engine behind
  "find candidates fast" (QV-039 saved-screens + QV-040 UI build on it).
- **Allow-list DSL** (`analytics/screener.py`, security core): `FIELDS`/`CATEGORICAL` maps + `NUMERIC_OPS`.
  A user filter's **field is a dict-key lookup** (unknown → `ScreenerError` → 422) and only the **trusted
  mapped column token** is interpolated; the operator is likewise allow-listed; **every value is a bound
  parameter**. Numeric fields require numeric values (a `"70; DROP…"` string fails validation); categorical
  values are bound literals. **Self-security-review:** the *only* SQL-interpolated tokens are hardcoded
  allow-list entries + bound `:params` (`:market`/`:limit`/`:offset` too) — no raw user text reaches SQL.
- **`screen(...)`** (`analytics/repositories.py`): a `screened` CTE assembling the LATERAL latest-score +
  open-fundamentals row per stock, then the built `WHERE`/`ORDER BY` (NULLS LAST) + `COUNT(*) OVER()` for
  `meta.count` + `LIMIT/OFFSET`. One pass, bounded universe → well under 1s (US-01).
- **`POST /screener`** (auth): validated body → `Envelope[list[ScreenerRow]]` + `meta{count, next_cursor,
  disclaimer}` + disclaimer header. Opaque **offset-backed cursor** (base64) — pragmatic + correct for the
  bounded daily snapshot. `ScreenerError`/`InvalidCursor` → 422.
- **Honest limits:** fundamentals filters (`roe`/`pe`) match little until licensed data (QV-072); score/
  coverage filters work on the seeded scored universe today (nulls excluded by `>=` etc.). **Deferred:**
  a materialized/cached projection (perf, if the universe grows) + **keyset-on-sort** pagination (drift-free
  at scale) — both noted for `pending-verifications`. **Not this story:** saving screens (QV-039), the UI
  (QV-040), portfolio/optimize.

### File List

**New (backend/)**
- `src/quantvista/analytics/screener.py` (allow-list DSL) · `src/quantvista/schemas/screener.py` (DTOs)
- `src/quantvista/api/routes_screener.py` (POST /screener)
- `tests/test_screener_dsl.py` (unit) · `tests/integration/test_api_screener.py` (e2e)

**Modified (backend/)**
- `src/quantvista/analytics/repositories.py` (`screen(...)` + `_screener_row`)
- `src/quantvista/api/app.py` (register `screener_router`; `ScreenerError` → 422 handler)

**Modified (repo):** `_bmad-output/.../sprint-status.yaml` — QV-038 status; QV-037 → done (housekeeping).

### Change Log

- **2026-07-08 — QV-038 screener query engine + API.** `POST /screener` (`04` §3.4): validated `filters[]`
  + `sort` + cursor + `limit` over an **allow-list DSL** (fields/operators enumerated; values always bound —
  no injection surface), an assembled LATERAL row-per-stock query with `COUNT(*) OVER()` for `meta.count`,
  and opaque offset pagination. Auth-only (quotas = QV-039). No migration. 320 tests green (12 new; DSL +
  routes 100%/94%); ruff/mypy-strict/import-linter clean. QV-039 (saved screens) + QV-040 (UI) build on this.

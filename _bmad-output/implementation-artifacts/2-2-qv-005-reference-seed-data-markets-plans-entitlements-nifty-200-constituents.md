---
baseline_commit: 7994af54587e93577f00dba37a47bf439d9d2009
---

# Story 2.2: QV-005 — Reference seed data (markets, plans, entitlements, Nifty-200 constituents)

Status: review

## Story

As the **platform**,
I want **idempotent reference seed data — markets, plans, entitlements, and a point-in-time bootstrap Nifty-200 universe**,
so that **plans/markets/universe exist before any feature needs them, and re-running the seed is always a safe no-op**.

> Canonical ID **QV-005** · Epic 2 (EPIC-IDN) · `[DATA]` · 3pts · Sprint 00 · depends: **QV-004 (done)**
> Authoritative detail: `plans/sprints/sprint-00-foundations.md` §QV-005. PIT/data: `plans/03-data-architecture.md` §5.

## Acceptance Criteria

1. **markets / plans / entitlements are seeded idempotently** (this already exists in `seed_reference.sql` — verify, keep, and confirm idempotency): `markets` (NSE), `plans` (`free`/`pro`/`quant`), and per-plan `entitlements` matching the tier matrix.
2. **A point-in-time bootstrap Nifty-200 universe is seeded idempotently:** ~10–15 liquid Nifty large-caps into `stocks` (global, no `tenant_id`) and their **current** membership into `index_constituents` (`index_code = 'NIFTY200'`, `effective_from` set, `effective_to = NULL`). This is a **bootstrap subset only** — the full ~200 names + ongoing maintenance are **QV-019** (`sync_index_constituents`). Update the seed file's deferral comment to say so.
3. **Re-running the entire seed is a no-op** — no duplicate rows, no errors. Verified by running it twice and asserting row counts are unchanged.
4. **PIT-capable from the start** (`plans/03` §5): `index_constituents` rows carry `effective_from`/`effective_to` (current = `effective_to NULL`); `stocks` carry `listed_on`, `delisted_on` (NULL for active), `is_active`. No survivorship assumptions baked in.
5. **Reference data is global** — `markets`, `plans`, `entitlements`, `stocks`, `index_constituents` have **no `tenant_id` and no RLS**; they are written by the **privileged/admin role**, never a tenant session (project-context #1).
6. **No regressions:** existing gates stay green (ruff, mypy, pytest incl. the QV-004 RLS tests, import-linter); the seed continues to load via the compose `seed` one-shot and `psql -f`.

## Tasks / Subtasks

- [x] **Task 1 — Verify & confirm the existing markets/plans/entitlements seed** (AC: #1, #3)
  - [x] Review `backend/src/quantvista/db/seeds/seed_reference.sql` — markets (NSE), plans (free/pro/quant), entitlements (FREE/PRO/QUANT key sets). It already upserts via `ON CONFLICT … DO UPDATE`. Confirm it applies cleanly against the migrated schema and is idempotent on re-run.
- [x] **Task 2 — Bootstrap Nifty-200 universe seed (PIT)** (AC: #2, #4, #5)
  - [x] Append a **"BOOTSTRAP SUBSET"** section to `seed_reference.sql` (so the same `seed` step loads it) inserting ~10–15 liquid Nifty stocks into `stocks` (`market_id` = NSE's id via subquery; `symbol`, `company_name`, `sector`, `is_active = true`, `listed_on`). Idempotent via `ON CONFLICT (market_id, symbol) DO UPDATE` (the `stocks_market_id_symbol_key` unique constraint exists).
  - [x] Insert current `index_constituents` membership: `index_code = 'NIFTY200'`, `stock_id` (join `stocks` by symbol), `effective_from = DATE '2024-01-01'` (a documented bootstrap as-of date), `effective_to = NULL`, `weight = NULL`. **`index_constituents` has no unique key**, so make it idempotent with a guard: `INSERT … SELECT … WHERE NOT EXISTS (SELECT 1 FROM index_constituents ic WHERE ic.index_code='NIFTY200' AND ic.stock_id = s.id AND ic.effective_to IS NULL)`.
  - [x] Replace the old lines 88–89 comment with one clarifying: bootstrap current members seeded here; full ~200 names, historical PIT membership, and weights come from QV-019's `sync_index_constituents`.
- [x] **Task 3 — Idempotency + content test** (AC: #1, #2, #3, #4)
  - [x] Add `backend/tests/integration/test_seed_reference.py` (reuse the QV-004 integration harness / `admin_engine`). A fixture applies the seed twice (via `psql -f` or by executing the SQL file). Assert: NSE market present; plans `{free,pro,quant}`; entitlements rows per plan; ≥10 bootstrap stocks; NIFTY200 `index_constituents` rows with `effective_to IS NULL`; **counts identical after the second run** (idempotent).
  - [x] Mark `@pytest.mark.integration` (auto-skips without Postgres, per `conftest.py`).
- [x] **Task 4 — CI + docs** (AC: #3, #6)
  - [x] Extend the CI `backend-rls` job (or add a step): after `alembic upgrade head`, load the seed (`psql -f …/seed_reference.sql`) **twice**, then run `pytest -m integration` so the seed idempotency test runs against the service Postgres.
  - [x] Note the bootstrap-vs-QV-019 split in `backend/src/quantvista/db/README.md`. Re-run all gates green.

## Dev Notes

### Scope discipline (decided with the user)
**Bootstrap subset.** QV-005 keeps the existing markets/plans/entitlements seed and adds a **small** PIT Nifty universe (~10–15 names) so early manual/dev testing has stocks. The **full ~200-name NIFTY-200, historical PIT membership, weights, and ongoing sync are QV-019** (`sync_index_constituents`, Sprint 01) — do not fabricate 200 names or build a sync here. This resolves the conflict where `seed_reference.sql` previously deferred *all* constituents to QV-019.

### What already exists (verified)
- `seed_reference.sql` (89 lines) seeds **markets** (NSE), **plans** (`free`/`pro`/`quant`, `price_inr` placeholder), and **entitlements** for each plan (keys like `universe_scores_top`, `saved_screens`, `watchlists`, `optimization`, `backtest`, `api_access`, …; `limit_int NULL` = unlimited, `flag_bool` for capabilities). All upsert via `ON CONFLICT … DO UPDATE` → already idempotent. **Keep this; don't rewrite the matrix** (values mirror `plans/01-prd.md` §4 and are O3/config).
- The seed runs as a one-shot in compose (`seed` service on the `postgres` image, `psql -f`, QV-002) and locally via `psql "$ADMIN_DATABASE_URL" -f …`. It is wrapped in `BEGIN/COMMIT`.
- Schema (migration `0003`, already applied):
  - `stocks(id, market_id→markets, symbol, isin, company_name, sector, industry, market_cap_bucket, listed_on, delisted_on, is_active, …)`, **UNIQUE (market_id, symbol)**, global (no RLS).
  - `index_constituents(id, index_code, stock_id→stocks, effective_from NOT NULL, effective_to, weight)`, **no unique constraint**, global (no RLS).
- From QV-004: the integration test harness — `backend/tests/conftest.py` skips integration tests when no Postgres is reachable, exposes an `admin_engine` (privileged) fixture; `integration` marker registered; tests run as the admin role here (reference data is admin-written).

### Suggested bootstrap stock list (dev may adjust)
Liquid Nifty large-caps (symbol — company — sector), public/static (hand-entered, NOT scraped):
`RELIANCE` (Reliance Industries — Energy), `TCS` (Tata Consultancy Services — IT), `HDFCBANK` (HDFC Bank — Financials), `INFY` (Infosys — IT), `ICICIBANK` (ICICI Bank — Financials), `HINDUNILVR` (Hindustan Unilever — FMCG), `ITC` (ITC — FMCG), `SBIN` (State Bank of India — Financials), `BHARTIARTL` (Bharti Airtel — Telecom), `LT` (Larsen & Toubro — Industrials), `KOTAKBANK` (Kotak Mahindra Bank — Financials), `AXISBANK` (Axis Bank — Financials).

### Critical constraints
- **Data licensing (project-context #8):** a static, hand-curated list of public index membership + company names is fine for a seed. **Do NOT wire `yfinance`/scrapers** or any live vendor here — vendor ingestion is QV-012/QV-019 behind `IMarketDataProvider`.
- **Two domains (project-context #1):** everything seeded here is **global reference** — no `tenant_id`, no RLS, written by the **admin/privileged** role. Never seed via a tenant `session_scope`.
- **PIT (#4):** `effective_from` is a real date; `effective_to NULL` = current membership. Keep `stocks.delisted_on` available (NULL here) so survivorship-free history works later.
- **Idempotency:** `markets`/`plans`/`entitlements`/`stocks` use `ON CONFLICT … DO UPDATE`; `index_constituents` uses a `WHERE NOT EXISTS` guard (no unique key). Re-running the whole file must be a clean no-op (AC #3) — the test enforces this.
- **No new migrations** — the schema already exists; this is data only. (If you ever wanted a unique key on `index_constituents` for upserts, that's a QV-013/QV-019 schema concern, not QV-005.)

### Testing standards
- Integration (`-m integration`, Postgres-backed): apply the seed twice; assert presence + **count stability** across runs (idempotency is the headline AC). Reuse `admin_engine` from `conftest.py`.
- Keep it admin-role (reference data); no tenant context needed. Coverage isn't meaningful for SQL data, but the idempotency/content assertions are the real gate.

### Project Structure Notes
- Modified: `backend/src/quantvista/db/seeds/seed_reference.sql` (append bootstrap universe + fix deferral comment); `.github/workflows/ci.yml` (load seed ×2 in the DB job); `backend/src/quantvista/db/README.md` (bootstrap-vs-QV-019 note).
- New: `backend/tests/integration/test_seed_reference.py`.
- Do not touch migrations or the entitlement matrix values.

### References
- [Source: plans/sprints/sprint-00-foundations.md#QV-005]
- [Source: plans/03-data-architecture.md#5] — PIT / survivorship-free universe
- [Source: backend/src/quantvista/db/seeds/seed_reference.sql] — existing markets/plans/entitlements seed
- [Source: backend/src/quantvista/db/migrations/versions/0003_reference_market.py] — stocks / index_constituents schema
- [Source: _bmad-output/project-context.md#1] — global reference vs tenant domains; admin-written
- [Source: _bmad-output/project-context.md#8] — data-licensing (no scrapers in seed)
- [Source: _bmad-output/implementation-artifacts/2-1-qv-004-postgresql-alembic-rls-scaffolding.md] — integration harness, admin_engine, privileged writes

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Opus 4.8) via BMAD dev-story workflow.

### Debug Log References

- **Latent bug found & fixed:** the pre-existing markets/plans/entitlements seed had **never been run
  against a database** and failed on PostgreSQL — `VALUES` lists with bare `NULL` (`flag_bool`, and the
  all-NULL first rows of PRO/QUANT) left columns as `unknown`/`text`, so the insert into
  `integer`/`boolean` columns raised "could not determine type / rewrite or cast." Fixed at the source
  per user preference (see [[sql-type-ambiguity-at-source]]): typed the **first `VALUES` row** of each
  plan block (`50::int`, `NULL::boolean`), which anchors the derived-table column types — minimal and
  explicit, rather than casting in the outer SELECT.
- mypy `no-untyped-call` on a `lambda` helper in the test → replaced with a typed inner `def q(sql) -> int`.
- The seed test applies the seed via `psql -f` (subprocess) — same path compose/CI use — converting the
  SQLAlchemy `admin_database_url` to a libpq URL (strip `+psycopg`).

### Completion Notes List

- **All 6 ACs satisfied; all tasks complete. Status → review.** Gates green: ruff, ruff format,
  mypy --strict, import-linter, pytest **32 passed** (30 prior + 2 new seed tests) against local PG 18.4.
- **markets/plans/entitlements seed verified + fixed** (AC #1): now applies cleanly and idempotently
  (run-twice counts identical: markets=1, plans=3 `{free,pro,quant}`, entitlements=37 [11/13/13 per plan]).
- **Bootstrap Nifty universe** (AC #2,#4): ~12 liquid large-caps → `stocks` (idempotent via
  `ON CONFLICT (market_id, symbol)`) + current `NIFTY200` membership → `index_constituents`
  (`effective_from` set, `effective_to NULL`), idempotent via a `WHERE NOT EXISTS` guard (no unique key).
  Updated the seed's deferral comment: full ~200 + history + weights = QV-019.
- **Idempotency test** (AC #3): `tests/integration/test_seed_reference.py` applies the seed twice and
  asserts counts are unchanged + content present + PIT membership dated. Reuses the QV-004 `admin_engine`
  fixture + reachability gating; auto-skips without Postgres.
- **Global reference** (AC #5): all seeded data has no `tenant_id`/RLS, written by the admin role.
- **CI** (AC #4,#6): `backend-rls` job (renamed → "Backend DB (RLS + reference seed)") now loads the seed
  and runs `pytest -m integration` (RLS denial + seed idempotency) against the Postgres service.
- **No new migrations, no new deps**; entitlement matrix values untouched (only the first-row type casts).

### File List

**Modified:**
- `backend/src/quantvista/db/seeds/seed_reference.sql` (fix VALUES type inference at source; append bootstrap Nifty universe; update deferral comment)
- `.github/workflows/ci.yml` (`backend-rls`: load seed + run seed idempotency test; job renamed)
- `backend/src/quantvista/db/README.md` (reference-seed note: bootstrap vs QV-019)

**New:**
- `backend/tests/integration/test_seed_reference.py`

**Process:**
- this story file (frontmatter `baseline_commit`, tasks, Dev Agent Record, Status); `sprint-status.yaml`

## Change Log

| Date | Change |
|------|--------|
| 2026-06-20 | QV-005 implemented: fixed + verified the markets/plans/entitlements seed (latent `VALUES`/NULL type bug, fixed at source); added an idempotent PIT bootstrap Nifty universe (~12 names, current `NIFTY200` membership; full set deferred to QV-019); seed idempotency integration test; CI loads the seed and runs it in the `backend-rls` DB job. All gates green (32 tests). Status → review. |

---
baseline_commit: 113ce10e4c4f9216ebade57c7186b7ce33ed0690
---

# Story 3.18: QV-092 — Dev universe expansion to full Nifty 200 (yfinance)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a developer/operator**,
I want **the dev universe expanded from the 12-stock bootstrap to the full Nifty 200 via yfinance**,
so that **the screener, rankings, and scoring exercise a realistic universe instead of a toy subset**.

> Canonical ID **QV-092** · Epic 3 (EPIC-DATA) · `[DATA]` · 3pts · depends: **QV-016 ✅** (price backfill), **QV-019 ✅** (constituent model), **QV-030 ✅** (factor/score jobs).
> **Why now:** the full 200 was architecturally deferred to **QV-072** (licensed vendor), but that is **blocked** — the TrueData free trial is **real-time only** (no historical backfill; verified 2026-07-10), and our EOD scoring needs ~400d of history. yfinance already serves EOD history (free, T-1, dev-only), so we bring the 200 in that way. QV-072 stays in the backlog for when a paid historical plan or another vendor is available.

## What exists (reuse)

- **Universe read** — `active_universe(session, index_code, market)` (`market_data/repositories.py`) reads the **DB's** `index_constituents` (open members) + active `stocks`. The scoring pipeline iterates *whatever is in the DB* — so expansion = loading the 200 constituents, then re-running the existing backfill/score pipeline.
- **Price backfill** — `backfill_daily_prices(market, start, end, index_code)` → `PriceIngestionService.ingest` (per-stock isolation, collects failures) → `daily_prices` upsert. Wrapped by `_run` which is **STRICT** (any `stocks_failed` aborts the run). yfinance symbol mapping via `yahoo_symbol` (`RELIANCE` → `RELIANCE.NS`).
- **Score pipeline** — `scripts/dev_backfill.py` already chains `backfill_daily_prices → compute_indicators → compute_factors → compute_scores` over the DB universe. The compute steps operate over whatever prices exist (not per-stock STRICT).
- **Seed precedent** — `seed_reference.sql` seeds the 12-stock bootstrap + their `NIFTY200` membership (`effective_to NULL`, idempotent via `NOT EXISTS`). Sectors already use NSE macro-industry names (`Financial Services`, `Information Technology`, …) — the CSV's `Industry` column maps 1:1.
- **Provider stub** — `YFinanceDevProvider.list_universe` is a deliberate **5-symbol non-authoritative stub**, reserved for the licensed vendor (per QV-019). **We do not touch it.**

## Locked decisions

- **Bundle the constituent list, don't fetch at runtime.** NSE's official `ind_nifty200list.csv` (200 rows: Company Name, Industry, Symbol, Series, ISIN) is committed as dev reference data (`backend/scripts/data/nifty200.csv`) — reproducible, no dependency on NSE availability during a load.
- **Dev loader, provider stub untouched.** `scripts/load_nifty200_universe.py` idempotently upserts the 200 into `stocks` (market NSE; `sector = Industry`; `is_active = true`) + `index_constituents` (`NIFTY200`, `effective_from` fixed date, `effective_to NULL`, `weight` absent) — same ON-CONFLICT / NOT-EXISTS posture as the seed. The provider's `list_universe` stays the 5-symbol stub (the 200 enter as bundled dev reference data, **not** via the licensed-vendor sync seam). Pure `parse_nifty200_csv(text)` is unit-tested.
- **Tolerant bulk price load (dev-only).** 200 symbols × ~400d over yfinance *will* hit 429s / delisted-symbol gaps; production STRICT (abort-on-any-failure) is wrong for a dev bulk load. `dev_backfill.py` gains a path that runs the price step **tolerantly** — call `PriceIngestionService.ingest` directly, log the per-stock failures, and continue to indicators/factors/scores over the names that loaded. Production `backfill_daily_prices`/`_run` STRICT is **not** weakened.
- **Ceiling unchanged, breadth widened.** Scores stay momentum + risk only (no fundamentals — separate vendor story), no index weights, current-snapshot membership (not point-in-time history). 12 → ~200 names.

## Acceptance Criteria

1. **Bundled list.** `backend/scripts/data/nifty200.csv` committed (200 constituents); `parse_nifty200_csv` parses it to typed rows (symbol, company, industry/sector, isin), unit-tested (count + shape + a spot-check row).
2. **Idempotent loader.** `scripts/load_nifty200_universe.py` upserts the 200 into `stocks` + `NIFTY200` `index_constituents`; running it twice leaves counts unchanged (no duplicate open memberships). Provider `list_universe` unchanged.
3. **Tolerant backfill.** `dev_backfill.py` loads prices for the 200 in tolerant mode (per-stock isolation; failures logged, run not aborted), then computes indicators → factors → scores over the loaded names. Production STRICT path untouched.
4. **Universe live.** After a run, `active_universe('NIFTY200','NSE')` returns ~200 (minus any Yahoo-unavailable drops), `scores` has rows for a substantial majority, and `/rankings` / `/screener` return the expanded set.
5. **Gates.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green (new pure logic covered). No new migration (reference-data load, not schema).

## Tasks / Subtasks

- [x] **Task 1 — bundle + parser** (AC: #1, #5)
  - [x] Committed `backend/scripts/data/nifty200.csv` (NSE official list, 200 rows). `parse_nifty200_csv(text) -> list[ConstituentRow]` (pure) + unit tests (sample maps/skips blanks; bundled CSV = 200 unique symbols, RELIANCE present, all have company+ISIN).
- [x] **Task 2 — idempotent loader** (AC: #2)
  - [x] `scripts/load_nifty200_universe.py`: bundled CSV → upsert `stocks` (ON CONFLICT `(market_id,symbol)`, sets isin/company/sector) + `index_constituents` (`NIFTY200`, NOT-EXISTS open-membership guard, `RETURNING` count); privileged session; `--market`. Live: 200 stocks, +188 memberships → 200 open; re-run added 0 (idempotent).
- [x] **Task 3 — tolerant dev backfill** (AC: #3)
  - [x] `dev_backfill.py --tolerant`: direct `PriceIngestionService.ingest` (per-stock isolation, logs `failures`, no STRICT abort), then indicators/factors/scores. Production `backfill_daily_prices`/`_run` STRICT untouched.
- [x] **Task 4 — run + verify + gates** (AC: #4, #5)
  - [x] Loaded 200 + ran `--tolerant` backfill: prices 200/200 ok (0 failed, 54,325 rows) → indicators 200 → factors 988 → scores 200 (date 2026-07-09). Verified: `active_universe`=200, scored=200, `/screener` composite≥0 → 200 rows, `/rankings` → 50 (Free cap). Gates green. QV-040 → done reconciled on this branch.

## Dev Notes

### Loader
Read the bundled CSV (not the network). `sector = Industry` (already the convention). `effective_from` a fixed historical date (e.g. `2024-01-01`, matching the seed) so membership is stable; `effective_to NULL` = open. No `weight` (Yahoo/CSV has none). Mirror the seed's idempotency: `INSERT … ON CONFLICT (market_id, symbol) DO UPDATE` for stocks; `NOT EXISTS` open-membership guard for constituents.

### Tolerant backfill (the crux)
Production `_run` raises on `report.stocks_failed` — correct for prod, fatal for a 200-symbol dev load where transient 429s and a few delisted/renamed tickers are expected. The dev path calls `PriceIngestionService.ingest(market, start, end, index_code="NIFTY200")` directly, logs `report.failures`, and proceeds regardless. Then `compute_indicators/compute_factors/compute_scores` run over the names that have prices. Expect the fetch to take several minutes and a handful of names to drop; that's acceptable for dev. Consider a modest inter-symbol courtesy delay if 429s dominate.

### Boundaries / not this story
No schema change, no touching `YFinanceDevProvider.list_universe` (licensed-vendor seam), no fundamentals (empty by design → separate vendor story), no index weights, no point-in-time membership history. Nifty 500 is a later step (same mechanism, bigger CSV).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** `ruff` + `ruff format --check` clean · `mypy --strict` Success (165 files) · `lint-imports` 3/3 ·
  `pytest` **327 passed / 4 skipped** (+2 new loader parser tests). Added `pythonpath = ["scripts"]` to
  pytest config so the dev-tooling parser is importable in unit tests (scripts/ was already in mypy scope).
- **mypy fix:** `Session.execute(...).rowcount` is untyped on `Result`; switched the membership insert to
  `RETURNING stock_id` + `len(.all())` for a typed added-count.
- **Live run (2026-07-10):** loader → 200 stocks / 200 open NIFTY200 (idempotent re-run +0). `--tolerant`
  backfill → **prices 200/200 ok, 0 failed, 54,325 rows** → indicators 200 → factors 988 → scores 200
  (2026-07-09). API: `/screener` composite≥0 = 200 (top FEDERALBNK 92.25); `/rankings` = 50 (Free cap).
- **TrueData context:** QV-072 (licensed vendor) stays blocked — free trial is real-time-only, no historical
  backfill (verified). yfinance serves EOD history for the full 200, so this unblocks universe breadth now.

### Completion Notes List

- **Dev universe is now the full Nifty 200** (was a 12-stock bootstrap) — the screener/rankings/scoring
  exercise a realistic universe. Pure yfinance path; **no schema change, no production-code change**.
- **Bundled NSE constituent snapshot** (`scripts/data/nifty200.csv`) + idempotent `load_nifty200_universe.py`
  (stocks + open NIFTY200 membership). The provider's `list_universe` **stub is untouched** — the 200 enter as
  bundled dev reference data, keeping the licensed-vendor sync seam (QV-019/072) reserved.
- **Tolerant bulk load** added to `dev_backfill.py` (`--tolerant`) for the 200-symbol yfinance fetch;
  production STRICT abort-on-failure is preserved for the real ingestion path.
- **Ceiling unchanged, breadth widened:** momentum + risk scores only (no fundamentals — [[dev-fundamentals-empty-by-design]],
  separate vendor story), no index weights, current-snapshot membership (not point-in-time). 12 → 200 names.

### File List

**New (backend/)**
- `scripts/data/nifty200.csv` — NSE official Nifty 200 constituent snapshot (dev reference data).
- `scripts/load_nifty200_universe.py` — idempotent dev loader (parser + upsert).
- `tests/unit/test_nifty200_loader.py` — parser unit tests.

**Modified (backend/)**
- `scripts/dev_backfill.py` — `--tolerant` price path (`PriceIngestionService` direct, per-stock isolation).
- `pyproject.toml` — `pytest … pythonpath = ["scripts"]` (dev tooling testable).

**Modified (repo):** `_bmad-output/.../sprint-status.yaml` — QV-092 added + status; QV-040 → done (reconcile on this branch).

### Change Log

- **2026-07-10 — QV-092 dev universe expansion to full Nifty 200 (yfinance).** Bundled NSE constituent
  snapshot + idempotent loader (stocks + open NIFTY200 membership; provider `list_universe` stub untouched) +
  `dev_backfill.py --tolerant` (per-stock isolation for the 200-symbol yfinance fetch; production STRICT
  intact). Live: 200/200 prices → indicators/factors/scores; `/screener` + `/rankings` now serve the real
  universe. Opened because QV-072 (licensed vendor) is blocked (TrueData free trial = real-time-only). Ceiling
  unchanged (momentum+risk only, no fundamentals/weights). No schema, no production-code change. 327 tests green.

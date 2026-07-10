---
baseline_commit: 0fa492e2db804311de201c0ad9aefa7dcd33b3b4
---

# Story 5.2: QV-042 — News tagging to stocks

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **ingested news linked to the right stock (precision over recall)**,
so that **per-stock feeds (QV-043) are relevant and unmatched news stays untagged, not mis-tagged**.

> Canonical ID **QV-042** · Epic 5 (EPIC-NEWS) · `[DATA]` · 3pts · depends: **QV-041 ✅** (news ingested).
> Authoritative: sprint-04 §QV-042 — *"Map articles to `stock_id` via symbol/ISIN/company-name matching; unmatched stored with `stock_id=NULL`. Precision over recall; ambiguous matches flagged."*

## What exists (reuse)

- **`news` table (0007)** — has a **single nullable `stock_id`** (`REFERENCES stocks(id)`; NULL = unmatched) + `ix_news_stock_id_published_at`. QV-041 ingests with `stock_id = NULL`. **This story sets it.** One stock per article (the schema is single-FK, not many-to-many) → tag the **primary** confident match. **No migration.**
- **`news` context + `NewsIngested` event (QV-041)** — `NewsIngestionService` emits `NewsIngested` after each ingest run; the QV-025 consumer pattern (`register_pipeline_consumers`, thin handlers that `.delay()` a task) is the wiring model.
- **Stocks catalog** — `stocks` (global): `symbol`, `isin`, `company_name`, `is_active`. The match source. `market_data/repositories.py` has reads (`active_universe`); this story adds a light **`stock_catalog(session)`** read (id/symbol/isin/company_name for active stocks).
- **Boundary** — `news` and `market_data` are **independent** (import-linter). So the **matcher stays pure in `news`** (takes the catalog as plain `StockRef` data); the **`tag_news` job** (composition root, may import both) reads the catalog from `market_data` and hands it to the matcher. news never imports market_data.

## Locked decisions

- **Text matcher (`news/tagging.py`), pure + precision-first.** `StockRef(stock_id, symbol, isin, company_name)`; `build_match_index(catalog)` precomputes normalized aliases; `match_text(text, index) -> UUID | None`. Signals, highest-precision first:
  - **Company-name phrase** — the normalized *core* name (strip `Ltd/Limited/Inc/Corporation/&/punctuation`, lowercase) matched as a **whole word-bounded phrase** in `headline + summary` (the primary signal — distinctive, low false-positive).
  - **Symbol** — whole-word, case-sensitive, **length ≥ 3** (drops noisy 2-char tickers like `LT`); headlines that print a ticker.
  - **ISIN** — exact substring (rare but unambiguous).
  - **Precision over recall / ambiguity:** collect the **distinct** stock_ids matched by any signal. **Exactly one → tag it. Zero or ≥2 → leave `NULL`** (never guess) and **flag** (count + log the candidates). Short-form names ("Reliance" for "Reliance Industries") that don't contain the full core are intentionally *not* matched — recall traded for precision (upgrade path below).
- **`NewsTaggingService(catalog)`** (in `news/services.py`) — builds the index once, iterates **untagged** news (`stock_id IS NULL`), matches, updates `news.stock_id`; returns `TagReport(tagged, ambiguous, unmatched)`. Idempotent (already-tagged rows untouched; re-run re-scans only NULLs).
- **`tag_news` job + trigger** — `jobs/news.py` `tag_news` task under `run_job` (`run_key = tag_news:{date}`): reads `stock_catalog` (market_data) → runs the service. Wired as a **`NewsIngested` consumer** (`on_news_ingested` → `tag_news.delay()`) so tagging auto-follows ingestion; also standalone/manually runnable. **No event emitted** (tagging is a DB update; QV-043 reads tagged news on demand; QV-044 sentiment is per-article, tagging-independent).
- **Not using Marketaux entities yet** — Marketaux returns exact NSE/BSE symbols per article, but QV-041 did **not** persist them (only headline/summary/url). Wiring entity-based tagging (near-exact) needs entity persistence in ingestion — a **documented precision upgrade** (own follow-up), out of this text-matching story.

## Acceptance Criteria

1. **Matcher.** `match_text` tags a confident single company-name/symbol/ISIN match; returns `None` (unmatched) on no match; returns `None` (ambiguous) when ≥2 distinct stocks match. Corporate suffixes normalized; 2-char symbols not matched. Pure + unit-tested (precision + ambiguity + no-match cases).
2. **Tagging service.** `NewsTaggingService.tag_untagged` sets `news.stock_id` for confident matches only, leaves the rest NULL, returns counts; idempotent (re-run doesn't change already-tagged rows or mis-tag).
3. **Catalog read.** `stock_catalog(session)` returns active stocks' `(id, symbol, isin, company_name)`; the job maps them to `news.StockRef` (news never imports market_data).
4. **Job + trigger.** `tag_news` runs under the job framework (`jobs_runs`, idempotent); `NewsIngested` → `tag_news.delay()` consumer registered. Manually runnable.
5. **Boundaries + gates.** Matcher/service/DTO in `quantvista.news`; job + catalog wiring in `quantvista.jobs`; `lint-imports` green (**news ⟂ market_data** preserved). `ruff` + `ruff format` + `mypy --strict` + `pytest` (≥80% new) green. No migration.
6. **Tests.** Unit: matcher (exact name, symbol, ISIN, suffix-normalize, ambiguous→None, short-symbol reject, no-match). **Integration (real PG):** seed stocks + news → `tag_news` tags the matchable, leaves ambiguous/unmatched NULL, idempotent re-run; cross-check a known stock.

## Tasks / Subtasks

- [x] **Task 1 — pure matcher** (AC: #1)
  - [x] `news/tagging.py`: `StockRef`, `MatchIndex`, `build_match_index`, `match_text` (normalize core name + text symmetrically so `Larsen & Toubro` → `larsen toubro`; whole-word phrase; symbol ≥3; ISIN; non-unique core dropped; ambiguous/none → `None`). 9 unit tests, **100% cov**.
- [x] **Task 2 — repo + service** (AC: #2)
  - [x] `news/repositories.py`: `iter_untagged_news` (`stock_id IS NULL`, newest-first) + `set_news_stock`. `news/models.py`: `UntaggedArticle` + `TagReport`. `news/services.py`: `NewsTaggingService(catalog)` + `tag_untagged(session) -> TagReport` (builds index once, tags confident matches, leaves rest NULL).
- [x] **Task 3 — catalog read + job + consumer** (AC: #3, #4)
  - [x] `market_data/repositories.py`: `CatalogStock` + `stock_catalog(session)`. `jobs/news.py`: `tag_news` task (`run_key tag_news:{ts}` — per-second so each ingest triggers a real pass) + `_run_tag` maps catalog → `news.StockRef`. `jobs/consumers.py`: `on_news_ingested` → `tag_news.delay()`, registered on `NewsIngested`.
- [x] **Task 4 — tests + gates + reconcile** (AC: #5, #6)
  - [x] `tests/integration/test_news_tagging.py` (real PG): distinct-name tag, ambiguous→NULL, unmatched→NULL, idempotent, task under `run_job`. Gates green. QV-041 → done reconciled on this branch.

## Dev Notes

### Matching (the core)
Normalize a company name to its *core*: lowercase, strip punctuation + trailing corporate suffixes (`ltd`, `limited`, `inc`, `corporation`, `corp`, `co`, `company`), collapse whitespace. Match the core as a **word-bounded phrase** in the lowercased `headline + " " + summary`. Symbols: match the raw uppercase token word-bounded, `len ≥ 3`. ISIN: exact. Union the distinct stock_ids; **tag iff exactly one** — this is the precision-over-recall rule and the ambiguity flag in one. O(articles × stocks) ≈ 176 × 200 substring checks — trivial; no index needed (KISS). Marketaux-entity tagging (near-exact) is the future precision boost once entities are persisted.

### Boundary
`news/tagging.py` is pure and imports nothing from `market_data`; it operates on `news.StockRef` data. The `tag_news` job (in `jobs`, the composition root) is the only place that reads `stocks` (via `market_data.stock_catalog`) and converts rows to `news.StockRef`. This keeps the `news ⟂ market_data` independence contract intact.

### Not this story
Many-to-many news↔stocks (an article about 2 stocks tags only its primary; a `news_stocks` join is a future schema change if per-stock feeds need multi-tag), Marketaux-entity tagging (needs entity persistence), the per-stock news **API + frontend feed / Overview ticker / Financial-News section** (QV-043), FinBERT sentiment (QV-044). No migration.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** `ruff` + `ruff format --check` clean · `mypy --strict` Success (173 files) · `lint-imports` 3/3
  (**news ⟂ market_data** preserved — the matcher is pure; only the `jobs` composition root reads the catalog) ·
  `pytest` **355 passed / 4 skipped** (12 new). `news/tagging.py` **100%** coverage.
- **Live-verified on real dev news:** ran `tag_news` over the 176 QV-041 articles → **22 tagged** to real Nifty
  stocks (TCS×6, BSE×5, Indian Bank×2, Coforge, Swiggy, JSW Steel, Biocon, MCX, Indian Hotels, Godrej
  Properties…), all correct; the ~154 untagged are US Reuters/CNBC + general market articles naming no single
  Indian stock — **precision over recall working** (better NULL than a wrong tag). Idempotent (re-run tagged 0).
- **Matcher bug caught by a test:** normalizing the catalog core name (`Larsen & Toubro` → `larsen toubro`) but
  matching raw text missed the `&`; fixed by normalizing the text symmetrically before phrase matching.
- **run_key granularity:** `tag_news` keys per-**second** (not per-day) — the `NewsIngested` consumer fires each
  ingest, and each run must tag whatever is currently untagged; the ledger would otherwise skip all but the
  first daily run. Safe because tagging is naturally idempotent (tagged rows are never re-read).

### Completion Notes List

- **News is now linked to stocks** — a pure, precision-first text matcher (`news/tagging.py`) tags each untagged
  article to a **single** confident stock (company-name phrase, symbol ≥3 chars, or ISIN); **zero or ≥2 distinct
  matches → left NULL** (ambiguous/unmatched, never guessed). Corporate suffixes normalized; non-unique core
  names dropped. `NewsTaggingService` updates `news.stock_id`; the `tag_news` job runs on `NewsIngested`.
- **Boundary held:** the matcher imports nothing from `market_data`; the `tag_news` job (composition root) reads
  `market_data.stock_catalog` and maps rows into `news.StockRef` — `news ⟂ market_data` independence intact.
- **No migration** (`news.stock_id` pre-exists, single FK) — an article tags its **primary** stock. Marketaux
  already returns exact NSE/BSE entities per article; **entity-based tagging** (near-exact) is the documented
  precision upgrade once entities are persisted.
- **Not this story:** many-to-many news↔stocks, Marketaux-entity tagging, the per-stock news **API + frontend
  feed / Overview ticker / Financial-News section** (QV-043), FinBERT sentiment (QV-044), live Beat cadence (PV-007).

### File List

**New (backend/)**
- `src/quantvista/news/tagging.py` (pure matcher) · `tests/test_news_tagging.py` · `tests/integration/test_news_tagging.py`

**Modified (backend/)**
- `src/quantvista/news/{models,repositories,services}.py` (`UntaggedArticle`/`TagReport`, `iter_untagged_news`/
  `set_news_stock`, `NewsTaggingService`)
- `src/quantvista/market_data/repositories.py` (`CatalogStock` + `stock_catalog`)
- `src/quantvista/jobs/news.py` (`tag_news` task + `_run_tag`) · `src/quantvista/jobs/consumers.py`
  (`on_news_ingested` → `tag_news`, subscribed to `NewsIngested`)

**Modified (repo):** `_bmad-output/.../sprint-status.yaml` (QV-042 status; QV-041 → done reconcile).

### Change Log

- **2026-07-11 — QV-042 news tagging to stocks.** A pure, precision-first text matcher (`news/tagging.py`) links
  untagged articles to a single `stock_id` via company-name / symbol(≥3) / ISIN matching — confident single
  match only; ambiguous or none → NULL. `NewsTaggingService` + `tag_news` job (on `NewsIngested`), fed the stocks
  catalog from `market_data` by the composition-root job (news never imports market_data). Live: 22/176 real dev
  articles tagged, all correct; idempotent. No migration. 355 tests green (12 new; matcher 100% cov);
  ruff/mypy-strict/import-linter clean. QV-043 (per-stock news feed + UI) builds on this.

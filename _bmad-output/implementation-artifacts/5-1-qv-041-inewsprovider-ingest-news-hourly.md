---
baseline_commit: ef0092cfb3eca7dc0b9ba6baebdc647e0b4e2d7a
---

# Story 5.1: QV-041 — INewsProvider + ingest_news (hourly)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **news ingested hourly through a provider-agnostic seam and stored deduped**,
so that **sentiment (QV-044) and per-stock feeds (QV-043) have input**.

> Canonical ID **QV-041** · Epic 5 (EPIC-NEWS) · `[DATA]` · 5pts · depends: **QV-015 ✅** (job framework), **QV-012 ✅** (provider-seam pattern).
> Authoritative: sprint-04 §QV-041 · `03` §1 rule 4 (store derived, link to original — no re-hosting) · `06` job catalog (`NewsIngested`).

## What exists (reuse)

- **`news` bounded context** (`quantvista.news`) — independent sibling of `market_data` (import-linter: they must not import each other; `news` may import `core`). Currently placeholder `models.py`/`repositories.py`/`services.py` + `interfaces.py` with `INewsService`/`ISentimentService` stubs. **This story fills them.**
- **`news` table (migration 0007, pre-exists)** — `id, stock_id (nullable → NULL=unmatched), headline NOT NULL, summary, source, source_url, published_at NOT NULL, language DEFAULT 'en', raw_ref, ingested_at`. **Dedup already modeled:** `uq_news_source_url` = partial UNIQUE on `source_url WHERE source_url IS NOT NULL`. Indexes on `(stock_id, published_at DESC)` and `(published_at DESC)`. **No new migration.**
- **Provider-seam template — `market_data/macro.py` (QV-026):** `IMacroProvider` Protocol + `FredMacroProvider` over a `_HttpJsonProvider` base (`ssl` + **certifi** CA bundle, retry, **injectable `urlopen`** → network-free tests), key from settings, raises without a key. QV-041 mirrors this for news (news-local HTTP base, since `news` can't import `market_data`).
- **Ingestion-service template — `PriceIngestionService`/`MacroSyncService`:** provider-agnostic service (depends only on the interface), per-item isolation, a frozen report DTO, emits via `self._events.publish("<Topic>", {...})`. Fake-provider + fake-event-bus unit tests.
- **Job framework (QV-015):** `run_job(name, run_key, work, ledger)` + `run_key(...)` (idempotent per key via `JobRunLedger`), Celery `@app.task` (autoretry), `beat_schedule` in `jobs/celery_app.py`. Task template = `jobs/macro.py`.
- **Config/events:** `core/config.py` `Settings` (add news keys); `get_event_bus()` (`core/events.py`); `privileged_session_scope()` (news is global/no-RLS, like market data).

## Locked decisions

- **`INewsProvider` seam (in `news/interfaces.py`)** — `get_news(query: str, since: datetime, until: datetime) -> Sequence[NewsArticle]`. Provider-agnostic: the ingestion service depends only on this. **Four dev-tier adapters** (user direction, 2026-07-11): `NewsApiProvider` (India-domain scoped), `GNewsProvider` (`country=in`), `MarketauxProvider` (`countries=in`; entities+sentiment for QV-042/044), `FinnhubProvider` (general, windowed). The service **fans out** over the enabled set (`news_providers`) via a `_REGISTRY`, deduping across all; adding a vendor = a new class + registry entry + its key, zero service/DB change. Per-provider key from `Settings` (raises without it, like FRED); network-free tested via injectable `urlopen`.
- **`NewsArticle` DTO (`news/models.py`)** — frozen dataclass: `headline, summary, source, source_url, published_at (datetime), language`. **Store derived + link, never re-host** (`03` §1 rule 4): headline + short summary + `source_url` only; full text is not stored. `raw_ref` (object-store capture) stays **NULL** this story (a lineage concern, deferred with QV-073).
- **Ingestion = broad market news, NOT per-stock** — tagging to `stock_id` is **QV-042**. QV-041 fetches a small fixed set of India-market queries (e.g. `NSE OR BSE OR Sensex OR Nifty`, `Indian stock market`) over the window and stores articles with **`stock_id = NULL`**. (Per-stock hourly queries would blow the free-tier cap; broad-then-tag fits QV-041→QV-042 and the 100-req/day free tier.)
- **Dedup + idempotency** — `upsert_news` = `INSERT … ON CONFLICT (source_url) WHERE source_url IS NOT NULL DO NOTHING RETURNING id` → **inserted count** (articles without a URL always insert). The **run** is idempotent via `run_key = news:{provider}:{hour-bucket}` + `JobRunLedger`. Overlapping windows are safe (URL dedup).
- **`NewsIngested` event** — emitted once per run with `{provider, since, until, fetched, inserted}` (string topic via the event bus, matching `PricesIngested`). Downstream trigger for QV-042 tagging.
- **Placement** — DTO + interface + provider + repo + service in `quantvista.news`; the `ingest_news` **task + hourly beat** in `quantvista.jobs.news` (composition root). Settings in `core/config.py`.

## Acceptance Criteria

1. **Provider seam + adapter.** `INewsProvider.get_news(...)` defined; `NewsApiProvider` maps the NewsAPI response → `NewsArticle` (network-free unit test via injected `urlopen`); raises a clear error when no `news_api_key` is configured.
2. **Store derived + dedup.** `upsert_news` writes `headline/summary/source/source_url/published_at/language` (never full text; `raw_ref` NULL), and de-duplicates on `source_url` (re-ingesting the same URL adds no row). Returns the true inserted count.
3. **Ingestion service.** `NewsIngestionService.ingest(...)` (provider-agnostic) fetches the market queries over the window, upserts deduped, emits **`NewsIngested`** with counts; per-query isolation (one failing query doesn't abort the run).
4. **Hourly job.** `ingest_news` Celery task under the job framework (`run_key` idempotent, recorded in `jobs_runs`), registered in Celery `include`. Intended cadence **hourly**, but — per the prices/macro convention — kept **off live Beat** until a `news_api_key` + scheduler exist (**PV-007**). `stock_id` left NULL (tagging = QV-042).
5. **Boundaries + gates.** All news code in `quantvista.news` (+ task in `quantvista.jobs.news`); `lint-imports` green (no `news`↔`market_data` import). `ruff` + `ruff format` + `mypy --strict` + `pytest` (≥80% new) green.
6. **Tests.** Unit: adapter parse + no-key error; service with a **fake provider + fake bus** (emits `NewsIngested`, counts). **Integration (real PG):** ingest → dedup (same URL twice = 1 row) → idempotent re-run.

## Tasks / Subtasks

- [x] **Task 1 — DTO + seam + adapter** (AC: #1)
  - [x] `news/models.py`: `NewsArticle` (frozen) + `NewsIngestReport`. `news/interfaces.py`: added `INewsProvider`. `news/providers.py`: news-local `_HttpJsonProvider` (certifi + retry + injectable `urlopen`) + `NewsApiProvider` (NewsAPI.org `/v2/everything`; key from settings; raises without it; in-body `status!=ok` → error). Unit tests: parse/skip-malformed, in-body-error, no-key.
- [x] **Task 2 — repo (dedup upsert)** (AC: #2)
  - [x] `news/repositories.py`: `upsert_news(session, articles) -> int` — `ON CONFLICT (source_url) WHERE source_url IS NOT NULL DO NOTHING RETURNING id`; true inserted count.
- [x] **Task 3 — ingestion service** (AC: #3)
  - [x] `news/services.py`: `NewsIngestionService(provider, event_bus)` + `MARKET_QUERIES`; `.ingest(since, until)` per-query isolation → `upsert_news` → emit `NewsIngested`; `NewsIngestReport`. Fake-provider + fake-bus unit tests (all-queries emit; failing-query isolation).
- [x] **Task 4 — task + config + gates** (AC: #4, #5, #6)
  - [x] `jobs/news.py`: `ingest_news` task + `_run_news` (`run_key news:{provider}:{hour}`) + `get_news_provider()` factory (unit-tested: newsapi resolves, unknown raises). Registered in Celery `include`; hourly Beat entry deferred to **PV-007** (off-beat, like prices/macro). `core/config.py`: `news_provider`, `news_api_key`. `celery_app` include + `pyproject` mypy override. Integration test (real PG): cross-query + cross-run dedup, `stock_id` NULL, task under `run_job`. Gates green. QV-092 → done reconciled on this branch.

## Dev Notes

### Provider-agnostic (the ask)
The seam is `INewsProvider`; the service never names a vendor. `NewsApiProvider` is the one concrete adapter (NewsAPI.org: `GET /v2/everything?q=&from=&to=&language=en&sortBy=publishedAt&apiKey=`; article → `title→headline`, `description→summary`, `source.name→source`, `url→source_url`, `publishedAt→published_at`). A Finnhub/GNews adapter later is a new class implementing the same Protocol + a factory branch — **zero service/DB change**. Key handling mirrors `FredMacroProvider` (raise if missing; tests inject `urlopen`, no key needed). News-local HTTP base (not shared with `market_data.macro` — the independence contract forbids importing it; a `core/http` consolidation is a future cleanup, out of scope).

### Dedup / store-derived
`source_url` is the natural key (`uq_news_source_url`). `ON CONFLICT … DO NOTHING RETURNING id` gives the real inserted count and makes overlapping hourly windows idempotent at the article level; the `run_key` makes the whole run idempotent. Store only headline + short summary + link (`03` §1 rule 4) — no full article text; `raw_ref` (object-store) is deferred.

### Boundaries / not this story
Ingestion + dedup + event only. **Not this story:** stock tagging (`stock_id` matching = QV-042), the per-stock news API + frontend feed (QV-043), FinBERT sentiment (QV-044), object-store raw capture (`raw_ref`, QV-073-adjacent), the sentiment factor (QV-046). `stock_id` stays NULL; a broad market-query fetch feeds QV-042.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** `ruff` + `ruff format --check` clean · `mypy --strict` Success (170 files) · `lint-imports` 3/3
  (incl. **news ⟂ market_data** independence) · `pytest` **343 passed / 4 skipped** (16 new). New-code coverage
  **95%** (`news` 93%, `jobs/news` 93%).
- **Multi-provider (user direction, 2026-07-11):** 4 dev-tier adapters behind `INewsProvider` — NewsAPI (scoped
  to Indian financial `domains=`), GNews (`country=in`), Marketaux (`countries=in`; also returns entities +
  sentiment → QV-042/044 seam), Finnhub (general, US-centric, windowed). Service **fans out** over the enabled
  set, deduping across all on `source_url`; per-(provider, query) isolation.
- **Live-verified (2026-07-11) — all 4 providers, 0 failures:** a real run ingested real India-financial
  articles — Times of India, BusinessLine, Livemint, Economic Times, Moneycontrol, Reuters/CNBC, + Marketaux
  (with NSE/BSE **entity mapping + sentiment scores**) — dedup + `NewsIngested` confirmed. Only Beat cadence
  remains → **PV-007**.
- **Marketaux two-bug fix (surfaced live):** (1) it sits behind **Cloudflare**, which blocked the default
  `Python-urllib` User-Agent (**CF error 1010**) → the HTTP base now sends a browser User-Agent (harmless for
  the others); (2) Marketaux rejects the `Z` suffix on `published_after`/`published_before` (`malformed_parameters`)
  → the adapter uses its `YYYY-MM-DDTHH:MM` format. Both proved that the per-provider isolation held live while
  it was failing (the other 3 kept ingesting).
- **Finnhub windowing:** its `/news` endpoint ignores the window and dumps its latest ~100 (US) each call — the
  adapter now filters to `[since, until]` so it behaves like a well-mannered windowed source.
- **Off-beat by convention:** data-ingestion jobs stay off live Beat until a scheduler (prices→PV-005,
  macro→PV-006); news hourly cadence → **PV-007**. Task is in Celery `include` (manually triggerable).
- **News-local HTTP base:** the `independence` contract forbids `news` importing `market_data.macro`, so the
  certifi+retry+injectable-`urlopen` base lives in `news/providers.py`. A `core/http` consolidation is future.

### Completion Notes List

- **Multi-source news ingestion behind a provider-agnostic seam** — `INewsProvider` + **4 adapters**
  (`NewsApiProvider`/`GNewsProvider`/`MarketauxProvider`/`FinnhubProvider`), `upsert_news` (dedup on
  `source_url`), `NewsIngestionService` fan-out (all enabled providers × market queries → dedup-upsert → emit
  `NewsIngested`), `ingest_news` hourly task. **No migration** (the `news` table pre-exists, 0007).
- **Provider-agnostic (the ask):** the service names no vendor; a new source = a new adapter + a `_REGISTRY`
  entry + its key in `Settings`, zero service/DB change. `get_news_providers()` builds the enabled set that has
  keys (skips keyless), so a missing/failing provider degrades gracefully. Keys via per-provider settings
  (aliased to the user's `.env` names); tests inject `urlopen`/fakes → no key needed.
- **Dev-grade sources, licensed posture:** all four free tiers are dev-only (NewsAPI explicitly) — stamped
  as such; production needs paid tiers, same rule as yfinance / QV-076. **Marketaux** is the standout for us
  (India + entity mapping + sentiment) — its entities/sentiment are the seam for QV-042/QV-044 (not consumed
  yet). **Finnhub** is US-centric (low India value) but included per direction.
- **Store derived + link (`03` §1 rule 4):** headline + short summary + `source_url` only; no full text;
  `raw_ref` NULL (object-store capture deferred). **`stock_id` NULL** — tagging = **QV-042** (`NewsIngested` triggers it).
- **Live-proven (all 4 providers, 0 failures):** real India-financial articles ingested incl. Marketaux with
  NSE/BSE entity mapping + sentiment; cross-provider dedup confirmed end to end. (Marketaux needed a Cloudflare
  browser-UA + its `YYYY-MM-DDTHH:MM` date format — both fixed; isolation held live while it was failing.)
- **Not this story:** stock tagging (QV-042), per-stock news API + the **Financial-News section / overview
  scrolling ticker** (QV-043 frontend), FinBERT sentiment (QV-044), the sentiment factor (QV-046), Marketaux
  entity/sentiment capture, live Beat cadence + Marketaux key (PV-007), object-store raw capture.

### File List

**New (backend/)**
- `src/quantvista/news/providers.py` (HTTP base + `NewsApiProvider`/`GNewsProvider`/`MarketauxProvider`/`FinnhubProvider`)
- `src/quantvista/jobs/news.py` (`ingest_news` + `get_news_providers` factory/registry)
- `tests/test_news_provider.py` · `tests/test_news_service.py` · `tests/integration/test_news_ingest.py`

**Modified (backend/)**
- `src/quantvista/news/{models,interfaces,repositories,services}.py` (filled placeholders: `NewsArticle`/
  `NewsIngestReport`, `INewsProvider`, `upsert_news`, multi-provider `NewsIngestionService`)
- `src/quantvista/core/config.py` (`news_providers` + per-provider keys, env-aliased) ·
  `src/quantvista/jobs/celery_app.py` (include `jobs.news`) · `pyproject.toml` (mypy override for `jobs.news`)

**Modified (repo):** `docs/pending-verifications.md` (**PV-007**) · `_bmad-output/.../sprint-status.yaml`
(QV-041 status + epic-5 in-progress; QV-092 → done reconcile).

### Change Log

- **2026-07-11 — QV-041 INewsProvider + ingest_news (hourly), multi-provider.** Provider-agnostic news
  ingestion behind `INewsProvider`, fanning out over **4 dev-tier adapters** — NewsAPI.org (India-domain
  scoped), GNews (`country=in`), Marketaux (`countries=in`, entities+sentiment), Finnhub (general, windowed) —
  with cross-provider dedup on `source_url` and per-provider isolation. `upsert_news`, `NewsIngestionService`
  (emit `NewsIngested`), `ingest_news` job (hourly, off live Beat → PV-007), `get_news_providers` registry.
  Stores derived + link only; `stock_id` NULL (tagging = QV-042). `news` table pre-exists (0007) — no migration.
  **Live-verified: all 4 providers, 0 failures** (Marketaux needed a Cloudflare browser-UA + its date format —
  fixed; it returns NSE/BSE entities + sentiment for QV-042/044). Only Beat cadence → PV-007. 343 tests green
  (16 new, 95% new-code cov); ruff/mypy-strict/import-linter clean. QV-042 builds on this.

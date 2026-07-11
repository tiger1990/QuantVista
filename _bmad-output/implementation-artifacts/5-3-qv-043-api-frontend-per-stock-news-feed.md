---
baseline_commit: 184f5d3f0306d3459f8edfbfe798e2e43946335e
---

# Story 5.3: QV-043 — API + Frontend: per-stock news feed (+ Financial News section & Overview ticker)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **recent news for a stock (and a market-wide news feed), history-windowed by my plan**,
so that **I have context on a name and on the market, safely rendered with links to the source**.

> Canonical ID **QV-043** · Epic 5 (EPIC-NEWS) · `[BE]` `[FE]` · 5pts · depends: **QV-041 ✅** (news ingested), **QV-042 ✅** (news tagged to stocks), **QV-036 ✅** (stock detail FE).
> Authoritative: sprint-04 §QV-043 — `GET /stocks/{symbol}/news` (history window per entitlement: **Free 7d / Pro 1y / Quant full**); news section on stock detail; **sanitized rendering, links out** (`07` §4 XSS-safe). · `01` §4 tiers.
> **User extensions (agreed):** a general **`GET /news`** feed → a **Financial News section** + a **scrolling ticker on Overview** (below the top-rated block), with India-source ranking so Finnhub's US items don't dominate.

## What exists (reuse)

- **`news` table (0007)** — populated by QV-041 (multi-provider, deduped) + tagged by QV-042 (`stock_id`). Indexes `ix_news_stock_id_published_at` + `ix_news_published_at` are exactly the read paths. Rows carry `headline, summary, source, source_url, published_at` (derived + link only — no full text).
- **`news_history_days` entitlement — already seeded** (Free 7 / Pro 365 / Quant NULL=unlimited). `EntitlementService.limit(tenant_id, "news_history_days") -> int | None` gates the window (pattern: `routes_scores` rankings quota).
- **API scaffolding** — `Envelope`, `get_current_principal`/`get_tenant_context`, `get_global_session`, `get_entitlement_service`, the `X-QuantVista-Disclaimer` header + `meta.disclaimer` (`routes_stocks`/`routes_screener`). Cursor/`meta` helpers.
- **FE** — typed client (`gen:api`), `useStockDetail`/`useStocks` hook patterns, `Card`, `Disclaimer`, `formatScore`, the stock-detail page (add a News section) + `dashboard.tsx` (add the ticker). `AppNav` `LINKS` (add **News**).

## Locked decisions

- **Reads in `news` (SQL-join `stocks` by symbol — allowed; no Python import of `market_data`).** `news/repositories.py`: `news_for_stock(session, symbol, since, limit)` (join `stocks` on symbol, `stock_id` match + `published_at >= since`, newest-first) and `latest_news(session, since, limit)` (market-wide, newest-first). `NewsItem` DTO in `schemas/news.py` (`id, headline, summary, source, source_url, published_at`).
- **Endpoints (`api/routes_news.py`, auth):**
  - `GET /api/v1/stocks/{symbol}/news?limit` → window = `today - news_history_days` (NULL = no lower bound); `Envelope[list[NewsItem]]` + disclaimer. Unknown symbol → empty list (200, not 404 — the stock may just have no tagged news).
  - `GET /api/v1/news?limit` → market-wide latest (same entitlement window applied); powers the Financial News section + ticker.
- **India-source ranking (general feed).** Order `latest_news` by `published_at DESC` but **de-prioritize US-centric Finnhub sources** so the market feed reads India-first — a small `ORDER BY (source IN (<indian publishers>)) DESC, published_at DESC` or a source-rank; Finnhub US items sink below Indian ones within the window.
- **XSS-safe rendering (`07` §4).** `headline`/`summary` are plain text → React escapes them by default (no `dangerouslySetInnerHTML`). Every source link opens with `target="_blank" rel="noopener noreferrer"`. We already store derived text + the link only — nothing to sanitize beyond safe rendering.
- **Frontend surfaces:**
  - **Stock detail** — a "Recent news" `Card` section (headline → source link, source · relative time), empty-state when none.
  - **Overview** — a compact **scrolling news ticker** below the top-rated block (latest headlines, link out).
  - **News page** (`/news`, nav item **News**) — the **Financial News section**: a readable list of latest market news (source, time, link), India-first.
- **Placement.** Reads/DTO in `quantvista.news` + `schemas`; route in `api/routes_news.py` (registered in `app.py`); FE hooks in `lib/api/queries.ts`, components under `features/news/*`, pages `stocks/[symbol]` (section) + `app/(app)/news/page.tsx` + `dashboard.tsx` (ticker). No migration.

## Acceptance Criteria

1. **Per-stock API.** `GET /stocks/{symbol}/news` returns that stock's tagged news, **windowed by `news_history_days`** (Free 7d / Pro 1y / Quant full), newest-first, `Envelope[list[NewsItem]]` + disclaimer. Empty list for a symbol with no news.
2. **Market API.** `GET /news` returns market-wide latest news within the entitlement window, **India-source-first**, newest-first.
3. **Stock-detail section.** The detail page shows a "Recent news" section (headline links out `rel=noopener`, source · relative time); empty-state when none.
4. **Financial News + ticker.** A `/news` page (nav **News**) lists market news; the **Overview** shows a scrolling ticker of latest headlines below the top-rated block. Both link out safely.
5. **Boundaries + gates.** Reads/DTO in `news`/`schemas`; route in `api`; `lint-imports` green (news ⟂ market_data at import level). Backend `ruff`/`ruff format`/`mypy --strict`/`pytest` (≥80% new). Frontend `eslint`/`tsc`/`vitest`/`next build`. No migration.
6. **Tests.** **Integration (real PG):** seed stock + tagged/untagged news across dates → per-stock endpoint returns only that stock's news within the window (Free 7d cutoff drops older); `/news` India-first ordering. **FE:** news-list renders headline+link (`rel=noopener`), empty-state; ticker renders.

## Tasks / Subtasks

- [x] **Task 1 — reads + DTO + API** (AC: #1, #2)
  - [x] `schemas/news.py`: `NewsItem`. `news/repositories.py`: `news_for_stock` (SQL-join `stocks` by symbol) + `latest_news` (India-source-first via a static allowlist rank). `api/routes_news.py`: `GET /stocks/{symbol}/news` + `GET /news` (window via `news_history_days`); registered in `app.py`. Integration tests (3): window scoping, unknown→empty, India-first invariant.
- [x] **Task 2 — frontend data + stock-detail section** (AC: #3)
  - [x] Refreshed `openapi.json`/`gen:api`. `useStockNews`/`useLatestNews` hooks; `relativeTime` helper; `features/news/NewsList.tsx` (React-escaped text + `rel=noopener` links out); "Recent news" `Card` on the stock-detail page. 3 NewsList component tests.
- [x] **Task 3 — News page + Overview ticker** (AC: #4)
  - [x] `app/(app)/news/page.tsx` (Financial News) + **News** nav link; `features/news/NewsTicker.tsx` (marquee, pause-on-hover, `motion-safe` only) + `ticker` keyframes in `globals.css`, mounted on Overview below the top-ranked grid.
- [x] **Task 4 — gates + reconcile** (AC: #5, #6)
  - [x] Backend ruff/mypy-strict/import-linter clean, `pytest` 358. Frontend eslint/tsc/vitest 49/next-build clean. Live-verified both endpoints. QV-093 → done reconciled on this branch.

## Dev Notes

### Window / entitlement
`limit = entitlements.limit(ctx.tenant_id, "news_history_days")`; `since = None if limit is None else date.today() - timedelta(days=limit)`. Reads filter `published_at >= since` (or no lower bound when unlimited). A hard `limit` (e.g. ≤100) caps rows regardless.

### India-first ordering (general feed)
Keep it simple: a source allowlist of Indian publishers (Economic Times, Moneycontrol, Livemint, BusinessLine, Business Standard, Times of India, Financial Express, Business Today) → `ORDER BY (lower(source) LIKE ANY(...)) DESC, published_at DESC`. Finnhub's Reuters/CNBC/Bloomberg sink below Indian items within the window (kept, not dropped — US macro still matters, per the Finnhub decision).

### Rendering / safety
Plain-text headline+summary → React escapes; no `dangerouslySetInnerHTML`. Source link: `<a href={source_url} target="_blank" rel="noopener noreferrer">`. Relative time via a tiny helper (e.g. "3h ago"). `Disclaimer` on news surfaces (research-only).

### Boundaries / not this story
`news_for_stock` may SQL-join `stocks` (the `news.stock_id` FK already ties them) — this does **not** import `market_data` (independence contract is import-level). **Not this story:** FinBERT sentiment on the cards (QV-044), news search/filtering, pagination beyond a simple limit, per-source logos, real-time push. No migration.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** backend `ruff` + `ruff format` + `mypy --strict` (176 files) + `lint-imports` 3/3 (**news ⟂ market_data**
  preserved — `news_for_stock` SQL-joins `stocks` but imports no market_data Python) + `pytest` **358**; frontend
  `eslint` 0 + `tsc` clean + `vitest` **49** (3 new) + `next build` clean (`/news` prerendered).
- **Live-verified:** `/news?limit=6` → India sources first (Moneycontrol, Business Today, Times of India, Economic
  Times) — US wire (Reuters/CNBC) correctly sunk below; `/stocks/TCS/news` → 6 tagged articles (Economic Times,
  Livemint, BusinessLine). Free-tier 7-day window applied.
- **India-first test robustness:** the market feed is global, so a fixed-`limit` response can't guarantee our
  seeded rows appear amid the ~176 ambient dev articles. Rewrote the assertion as an **ordering invariant** (every
  India-source row precedes every non-India row), classifying with the repo's own `_INDIA_SOURCES` allowlist so
  test and query agree — deterministic on a clean CI DB and against ambient dev data.

### Completion Notes List

- **News is now visible in the UI.** `GET /stocks/{symbol}/news` (per-stock, tagged via QV-042) and `GET /news`
  (market-wide, India-source-first) — both **entitlement-windowed** by `news_history_days` (Free 7d / Pro 1y /
  Quant unlimited). **No migration** (reads over the existing `news` table).
- **Three FE surfaces:** a "Recent news" section on the **stock detail** page, a **`/news` Financial News** page
  (new **News** nav item), and a **scrolling ticker on Overview** below the top-ranked grid. All render plain text
  (React-escaped — no `dangerouslySetInnerHTML`) with source links opening `target="_blank" rel="noopener noreferrer"`
  (`07` §4 XSS-safe). Ticker animates `motion-safe` only + pauses on hover.
- **India-first, Finnhub kept:** the market feed ranks Indian publishers ahead of US wire sources (Reuters/CNBC/
  Bloomberg) but keeps them (US macro moves Indian markets — the QV-041 decision).
- **Not this story:** FinBERT sentiment on the cards (QV-044), news search/filter, richer pagination, per-source
  logos, real-time push. Marketaux entity-based tagging remains the future precision upgrade for QV-042.

### File List

**New (backend/)** `schemas/news.py` · `api/routes_news.py` · `tests/integration/test_api_news.py`
**Modified (backend/)** `news/repositories.py` (`news_for_stock`/`latest_news` + `_INDIA_SOURCES`) · `api/app.py` (register news router)

**New (frontend/)** `features/news/{NewsList.tsx, NewsList.test.tsx, NewsTicker.tsx}` · `app/(app)/news/page.tsx`
**Modified (frontend/)** `lib/api/queries.ts` (`useStockNews`/`useLatestNews`, `NewsItem`) · `lib/utils.ts` (`relativeTime`) ·
`app/(app)/stocks/[symbol]/page.tsx` (Recent news) · `app/(app)/page.tsx` (ticker) · `components/app-nav.tsx` (News link) ·
`app/globals.css` (`ticker` keyframes) · `lib/api/{openapi.json, schema.d.ts}` (regenerated)

**Modified (repo):** `_bmad-output/.../sprint-status.yaml` (QV-043 status; QV-093 → done reconcile).

### Change Log

- **2026-07-11 — QV-043 news feed API + frontend.** `GET /stocks/{symbol}/news` (per-stock, QV-042 tags) + `GET /news`
  (market-wide, India-source-first), both windowed by `news_history_days` (Free 7d / Pro 1y / Quant full). FE: Recent-news
  section on stock detail, a `/news` Financial News page (nav), and an Overview scrolling ticker — XSS-safe (React-escaped
  + `rel=noopener`). Reads over the existing `news` table (no migration); `news ⟂ market_data` preserved. 358 backend + 49
  frontend tests green; all gates clean. FinBERT sentiment (QV-044) is next.

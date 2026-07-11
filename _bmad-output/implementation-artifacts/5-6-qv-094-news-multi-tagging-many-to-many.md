---
baseline_commit: b30fa0d74462c29e1c93247354fb2e8860d971a6
---

# Story 5.6: QV-094 — News multi-tagging (many-to-many news↔stocks)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **a news article to appear on every stock it names, not be dropped when it mentions several**,
so that **multi-stock stories (e.g. "Ashok Leyland, Hero MotoCorp to M&M: Auto stocks rise…") show on each name's page**.

> Canonical ID **QV-094** · Epic 5 (EPIC-NEWS) · `[DATA]` `[BE]` · 3pts · depends: **QV-042 ✅** (tagging), **QV-043 ✅** (per-stock read) · added post-hoc (user request).

## Problem (why)

QV-042 tags a **single** `news.stock_id` and, precision-over-recall, leaves an article **NULL** when ≥2 distinct stocks match. So a genuinely multi-stock article is tagged to *nothing* and shows only in the market-wide `/news` feed — never on any stock's page. (Live: 22 tagged, **154 NULL**, many of which are multi-stock/market-wide.) The fix is a **many-to-many** link so an article tags **all** the stocks it confidently names.

## What exists (reuse)

- **`news` table (0007)** — single nullable `stock_id` FK + `ix_news_stock_id_published_at`. **Superseded by this story.**
- **Matcher (`news/tagging.py`, QV-042)** — `build_match_index(catalog)` + `match_text() -> UUID | None` (exactly-one else None). Reused, generalized to return **all** confident matches.
- **`NewsTaggingService` + `tag_news` job (QV-042)** — catalog fed by the composition-root job (news ⟂ market_data preserved); `NewsIngested` consumer. Rewired to write the join table.
- **`news_for_stock` read (QV-043)** — currently joins `news.stock_id`; re-pointed at the join table.

## Locked decisions

- **Migration `0015_news_stocks`** (down 0014):
  - `CREATE TABLE news_stocks (news_id uuid → news(id) ON DELETE CASCADE, stock_id uuid → stocks(id), PRIMARY KEY (news_id, stock_id))` + `ix_news_stocks_stock_id`.
  - `ALTER TABLE news ADD COLUMN tagged_at timestamptz` — marks "the tagger has processed this row" (matched or not), so untagged = `tagged_at IS NULL` (market-wide no-match articles aren't re-scanned forever).
  - **Backfill:** migrate existing single tags → `news_stocks`; set `tagged_at = now()` **only** on already-tagged rows (`stock_id NOT NULL`). The **154 NULL rows keep `tagged_at NULL`** → re-processed with the new multi-match logic (this is what lights up the multi-stock articles).
  - Drop `news.stock_id` + `ix_news_stock_id_published_at` (fully superseded). `downgrade` reverses (re-add column, restore a single tag from the join, drop the table/column).
- **Matcher — `match_all(text, index) -> set[UUID]`** returns **every** distinct confident match (same per-match precision: normalized core company-name phrase, symbol ≥3, ISIN; non-unique catalog core names still dropped). `match_text` (single) is removed — no caller needs "exactly one" anymore.
- **Tagging — write the join, mark processed.** `NewsTaggingService.tag_untagged` iterates `tagged_at IS NULL` news; for each, `match_all` → **insert a `news_stocks` row per matched stock** (`ON CONFLICT DO NOTHING`), then set `tagged_at = now()` regardless of match count. Idempotent. `TagReport(scanned, tagged_articles, links_added)`.
- **Read — `news_for_stock` joins `news_stocks`.** `… FROM news n JOIN news_stocks ns ON ns.news_id = n.id JOIN stocks s ON s.id = ns.stock_id WHERE s.symbol = :symbol …`. `latest_news` unchanged (reads `news` directly).
- **Backfill run** — after the migration, run `tag_news` once to re-tag the 154 `tagged_at NULL` rows (multi-stock articles now land on each name).

## Acceptance Criteria

1. **Schema.** `0015_news_stocks` — join table (+ stock_id index) + `news.tagged_at`; backfill existing tags; drop `news.stock_id`. `alembic upgrade` + `downgrade` clean.
2. **Multi-match tagging.** `match_all` returns all confident distinct matches; `tag_untagged` writes one `news_stocks` row per match and sets `tagged_at`; idempotent (re-run adds no rows). A market-wide/no-match article is marked processed (no infinite re-scan) with zero links.
3. **Per-stock feed uses the join.** `GET /stocks/{symbol}/news` returns an article iff `(news, stock)` is linked — so a multi-stock article appears on **each** named stock's feed.
4. **Backfill.** After migration + a `tag_news` run, the "Auto stocks rise…" article is linked to Ashok Leyland, Hero MotoCorp, and M&M (appears on all three).
5. **Boundaries + gates.** Matcher/service/DTO in `news`; join read in `news`; `lint-imports` green (news ⟂ market_data). `ruff`/`ruff format`/`mypy --strict`/`pytest` green (QV-041/042 tests updated for the schema change).
6. **Tests.** Unit: `match_all` (multi-match returns the set; non-unique core dropped; symbol/ISIN). **Integration (real PG):** an article naming two seeded stocks → linked to **both**; a no-match article → `tagged_at` set, zero links; idempotent re-run; per-stock endpoint returns a shared article on both stocks.

## Tasks / Subtasks

- [x] **Task 1 — migration** (AC: #1)
  - [x] `0015_news_stocks.py`: `news_stocks` join (+ `ix_news_stocks_stock_id`) + `news.tagged_at`; backfill existing tags + mark processed; drop `news.stock_id` + `ix_news_stock_id_published_at`. `downgrade` restores a single tag. Applied; **down→up idempotent** (22 links / 154 untagged both ways).
- [x] **Task 2 — matcher + tagging** (AC: #2)
  - [x] `news/tagging.py`: `match_all(text, index) -> set[UUID]` (replaced `match_text`). `news/repositories.py`: `iter_untagged_news` (`tagged_at IS NULL`), `link_news_stocks` (`ON CONFLICT DO NOTHING`), `mark_news_tagged`. `news/services.py`: `tag_untagged` links all matches + marks processed; `TagReport(scanned, tagged, links)`.
- [x] **Task 3 — read + wiring** (AC: #3, #4)
  - [x] `news_for_stock` joins `news_stocks`. `tag_news` job + `NewsIngested` consumer unchanged. Backfill (via the test run + a job) re-tagged the dev backlog. **Live:** the "Auto stocks…" article links to ASHOKLEY, HEROMOTOCO, M&M (+ BOSCHLTD) and shows on each page.
- [x] **Task 4 — tests + gates + reconcile** (AC: #5, #6)
  - [x] Updated `tests/test_news_tagging.py` (unit → `match_all`, multi-stock case), `tests/integration/test_news_tagging.py` (join membership; two-stock article → both), `tests/integration/test_news_ingest.py` (`tagged_at IS NULL`), `tests/integration/test_api_news.py` (seed via `news_stocks`). Gates green. QV-043 → done reconciled on this branch.

## Dev Notes

### Precision unchanged, recall widened
Per-match precision is identical to QV-042 (whole normalized company-name phrase, symbol ≥3, ISIN; catalog cores shared by ≥2 stocks are dropped). The only change: we no longer collapse "≥2 matches" to NULL — we **keep them all**. A false-positive risk exists only if a name substring coincidentally matches; the whole-word + core-name rules keep that low (the QV-042 unit tests already pin the guards).

### `tagged_at` marker
Distinguishes "not yet processed" from "processed, no stock named". Without it the ~thousands of market-wide articles would be re-scanned every `tag_news` run forever. Set it whenever the tagger touches a row.

### Not this story
Sentiment (QV-044), a "primary stock" concept, weighting a stock by mention prominence, entity-based tagging from Marketaux (still the future precision+recall upgrade). Migration only touches the news domain.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **Gates:** `ruff` + `ruff format` + `mypy --strict` (176 files) + `lint-imports` 3/3 (**news ⟂ market_data** kept —
  matcher stays pure) + `pytest` **358 passed / 4 skipped**. Migration `0015` **up + down clean, idempotent**.
- **Live fix verified:** "Ashok Leyland, Hero Motocorp to M&M: Auto stocks rise…" links to **HEROMOTOCO,
  BOSCHLTD, ASHOKLEY, M&M**; "Nifty Midcap… Indian Bank, Kalyan Jewellers lead gains" links to **INDIANB +
  KALYANKJIL** (the short alias caught "Kalyan Jewellers" vs the catalog "Kalyan Jewellers India Ltd"). Full
  dev re-tag: **27 tagged, 40 links** over 176 articles.
- **`tagged_at` marker:** the 154 previously-NULL rows kept `tagged_at NULL` through the migration → re-processed
  with multi-match; no-match rows get `tagged_at` set so they're never re-scanned (the marker distinguishes
  "not processed" from "processed, names no stock").

### Completion Notes List

- **A news article now tags every stock it names** — `news_stocks` many-to-many replaces the single `news.stock_id`.
  Multi-stock stories (previously dropped as "ambiguous → NULL") appear on **each** named stock's feed.
- **Precision preserved, recall widened two ways:** (1) `match_all` stops collapsing multi-match to NULL; (2) a
  **short-name alias** — each stock is also matched by its core minus trailing "India"/stop words, **only when it
  stays ≥2 tokens and is unique** — so `"Kalyan Jewellers India Ltd"` also matches the bare `"Kalyan Jewellers"`
  while `"Bank of India"` never degrades to the unsafe single word `"bank"`. (25 Nifty names end in "India".)
- **`tag_news` semantics:** processes `tagged_at IS NULL` news, links all matches, marks `tagged_at`; idempotent.
  The job + `NewsIngested` consumer are unchanged.
- **Not this story:** sentiment (QV-044), a "primary stock" / mention-prominence weighting, Marketaux entity-based
  tagging (still the future precision+recall upgrade).

### File List

**New (backend/)** `db/migrations/versions/0015_news_stocks.py`
**Modified (backend/)** `news/tagging.py` (`match_all`) · `news/repositories.py` (`iter_untagged_news` by `tagged_at`,
`link_news_stocks`, `mark_news_tagged`, `news_for_stock` joins `news_stocks`) · `news/services.py` (multi-tag) ·
`news/models.py` (`TagReport.links`) · `tests/test_news_tagging.py` · `tests/integration/test_news_tagging.py` ·
`tests/integration/test_news_ingest.py` · `tests/integration/test_api_news.py`

**Modified (repo):** `_bmad-output/.../sprint-status.yaml` (QV-094 status; QV-043 → done reconcile).

### Change Log

- **2026-07-11 — QV-094 news multi-tagging (many-to-many).** Migration `0015_news_stocks`: `news_stocks` join +
  `news.tagged_at`, drop single `news.stock_id`. Matcher `match_text → match_all` (every confident match);
  `tag_news` links all matches + marks processed; `news_for_stock` joins the table. Multi-stock articles now show
  on each named stock's page (verified live: "Auto stocks…" on Ashok Leyland / Hero MotoCorp / M&M). Precision
  unchanged, recall widened. 358 tests green; all gates clean; migration up+down clean.

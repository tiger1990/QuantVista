---
baseline_commit: c8c2e65
---

Status: review

# QV-046 — Sentiment factor wired into scoring

**Epic:** EPIC-INTEL · **Points:** 3 · **Depends:** QV-044 (sentiment ✓), QV-045 (impact ✓), QV-029 (score engine ✓)

## Story

As a quant, I want sentiment in the composite, so scores reflect news — and so the stock-detail sentiment score and the composite finally light up in the UI (null today: no sentiment factor exists).

## Acceptance Criteria

1. A `SentimentFactor` (category `SENTIMENT`, direction +1) aggregates each stock's **decayed** per-article news signal (QV-045 `impact_score` = sentiment + event impact) **as-of date**, via the `ScoringContext` PIT gateway.
2. **PIT-safe:** only news `published_at <= as_of` and sentiment **known by** end of the as-of day (`created_at`); a stock with no visible news → factor `None` (excluded, category re-normalizes — no fabricated zero).
3. Recency **decay:** older news weighs less (exponential half-life); the factor is a decay-weighted mean.
4. Included at the plan §2 **10%** sentiment weight (already in `DEFAULT_WEIGHTS`); `FactorEngine` normalizes it (sector-z → percentile) like every other factor; `ScoreEngine.compute_scores` consumes it → `scores.sentiment_score` populated and the **decomposition** shows its contribution (Σ == composite).
5. Bounded-context: `analytics` may read `news` (it's a lower layer); the `news ⟂ market_data` contract is untouched. No migration.

## Tasks / Subtasks

- [x] **Task 1 — PIT sentiment read** (AC: #1, #2)
  - [x] `news/repositories.py`: `sentiment_signal_for_stock(session, stock_id, known_by)` — `news_stocks`-tagged news `published_at <= known_by`, LATERAL latest sentiment per news `created_at <= known_by` with non-null `impact_score` → `[(published_at, impact_score)]`.
- [x] **Task 2 — decay aggregation (pure)** (AC: #3)
  - [x] `analytics/sentiment.py`: `decayed_sentiment(rows, as_of, half_life_days=7)` = Σ(wᵢ·impactᵢ)/Σwᵢ, `wᵢ=0.5^(age/half_life)`, `age=max(0, as_of−published)`; `None` if empty. 6 unit tests.
- [x] **Task 3 — context + factor wire-up** (AC: #1, #4)
  - [x] `ScoringContext.sentiment_as_of` (known-by end-of-as_of-day → `decayed_sentiment`). `SentimentFactor` (`key="sentiment"`, `SENTIMENT`, `+1`) → `ALL_FACTORS`. `scoring.py` docstring updated.
- [x] **Task 4 — tests + live + gates + reconcile** (AC: #2, #4)
  - [x] Integration `test_sentiment_factor.py`: `sentiment_as_of` PIT-bounded (future news + not-yet-known sentiment excluded → only the visible one); `compute_universe` → non-null `sentiment` sub-score, `sentiment` in decomposition (Σ==composite), good-news > bad-news. QV-037 leakage green. Scoring tests updated for the 11th factor (coverage 10/11). Live as-of 2026-07-11: **27 stocks got `sentiment_score`** (INFY 100), `score_of('INFY').sentiment=100`. Gates green. QV-045 → done reconcile on this branch.

## Dev Notes

### Almost everything is already wired
`DEFAULT_WEIGHTS.sentiment=0.10`, `FactorCategory.SENTIMENT`, `StockScore.sentiment`, `sub.get(SENTIMENT)`, and `_blend`'s re-normalization over scored categories all exist (QV-029). The composite already *reserves* 10% for sentiment and **drops** it when absent. So this story adds exactly one concrete factor; sentiment then flows into `sentiment_score` + decomposition + the (already-built) stock-detail/screener UI automatically.

### What the factor aggregates
Per stock, the QV-045 **`impact_score`** (−100..+100; already blends tone + event weighting, plan §2 "news sentiment + event impact") over the stock's tagged articles, decay-weighted by recency. The `FactorEngine` then winsorizes → sector-z → percentile like any factor, so absolute scale is irrelevant; direction +1 (more-positive news → higher score). One sentiment row per news (latest `created_at`) so coexisting `dev-lexicon-v1`/`finbert` versions don't double-count.

### PIT / leakage (05 §1.1)
Two guards, both bounded by `as_of`: **valid-time** `news.published_at <= as_of` (no future news) and **knowledge-time** `sentiment.created_at <= end-of-as_of-day` (a score can't see a sentiment row scored later). Mirrors the fundamentals bitemporal read; because dev sentiment was scored "now", scoring as-of a past session sees none (same timing note as QV-095) — compute as-of a knowledge-available date to see it live.

### Not this story
- Per-article sentiment badge on the news feed (a `news_for_stock` read + UI) — separate.
- Sentiment-alert rules (Epic 6). Learned decay / half-life tuning / confidence-weighting — later increments.
- `impact_version`-aware factor selection; provider sentiment. Deferred.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Gates: ruff + format clean · mypy clean (192 files) · import-linter 3/3 (analytics→news allowed; `news ⟂ market_data` holds) · pytest **407 passed / 5 skipped** (+6 decay unit + 2 sentiment-factor integration).
- Live as-of 2026-07-11: `compute_factors`/`compute_scores` → **27/200 stocks have `sentiment_score`** (only those named in the 176 dev news articles; rest have no tagged news → factor None → excluded, coverage re-normalizes). Top: INFY 100, INDIANB/HDFCBANK/ICICIBANK 90.4. `score_of('INFY').sentiment == 100.0` (was null) — the stock-detail/screener sentiment now renders.

### Completion Notes List

- **Almost entirely a wire-up:** the 10% weight, `SENTIMENT` category, `StockScore.sentiment`, and `_blend` re-normalization were already in place (QV-029) — this added exactly one concrete `SentimentFactor` and the PIT read behind it. Sentiment then flows into `sentiment_score` + decomposition + the already-built UI with no engine/schema change.
- **Aggregates the QV-045 `impact_score`** (tone + event impact, plan §2 "news sentiment + event impact"), decay-weighted (7-day half-life); the `FactorEngine` normalizes it (sector-z→percentile) like any factor, so the −100..100 scale is irrelevant. One sentiment row per news (latest `created_at`) so dev/finbert versions don't double-count.
- **PIT (two guards, both ≤ as_of):** valid-time `news.published_at` and knowledge-time `sentiment.created_at`. Integration test proves a future-published article and a sentiment scored after as_of are both excluded. Same timing note as QV-095: dev sentiment scored "now" is only visible to scoring as-of a knowledge-available date.
- **Existing scoring tests updated:** adding an 11th factor changed coverage denominators; tests that seed fundamentals+indicators but no news now expect the sentiment factor absent (coverage 10/11) via a `_DATA_FACTORS` helper, and `test_factors` expects all 5 categories covered.

### File List

- `backend/src/quantvista/analytics/sentiment.py` (new) — pure `decayed_sentiment`
- `backend/src/quantvista/analytics/context.py` — `ScoringContext.sentiment_as_of` (imports `news`)
- `backend/src/quantvista/analytics/factors.py` — `SentimentFactor` → `ALL_FACTORS`
- `backend/src/quantvista/analytics/scoring.py` — docstring (sentiment factor now exists)
- `backend/src/quantvista/news/repositories.py` — `sentiment_signal_for_stock` (PIT)
- `backend/tests/test_sentiment_decay.py` (new), `backend/tests/integration/test_sentiment_factor.py` (new)
- `backend/tests/test_factors.py`, `tests/integration/test_scoring.py`, `tests/integration/test_scoring_jobs.py` — updated for the 11th factor

### Change Log

- QV-046: Sentiment factor wired into scoring — `SentimentFactor` aggregates each stock's decayed per-article news signal (QV-045 `impact_score`) PIT-safely via `ScoringContext.sentiment_as_of`; consumed by the existing 10%-weighted `ScoreEngine` → populates `scores.sentiment_score` + decomposition → surfaces in stock-detail/screener/composite. Pure `decayed_sentiment` (7-day half-life). No migration.

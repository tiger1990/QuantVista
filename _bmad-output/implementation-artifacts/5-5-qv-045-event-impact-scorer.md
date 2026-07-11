---
baseline_commit: b320543
---

Status: done

# QV-045 — Event-impact scorer

**Epic:** EPIC-NEWS (Epic 5) · **Points:** 3 · **Depends:** QV-044 (sentiment ✓)

## Story

As an analyst, I want material events weighted, so big news moves the signal appropriately — a "wins ₹X order" or a regulatory ban should carry more than raw tone.

## Acceptance Criteria

1. A pure, deterministic **event classifier** maps a news headline/summary to an **event type** from a versioned taxonomy (contract win, earnings beat/miss, upgrade/downgrade, regulatory action/ban, fraud/litigation, M&A, capital action, default/distress, management change, NONE).
2. A **versioned, configurable** map assigns each event type a signed **base impact** (e.g., contract win **+25**, ban **−40**, per plan §1.4). `IMPACT_RULESET_VERSION = "impact-v1"`.
3. `EventImpactScorer.score(text, sentiment) -> Decimal` **combines** the base impact with the QV-044 sentiment into an `impact_score`, clamped to a bounded scale (≈ [−100, 100]); pure/None-safe, deterministic.
4. Scoring **persists `impact_score`** onto the existing `sentiment` row (0007 column) in the same pass as sentiment — idempotent per `(news_id, model_version)`. **No migration.**
5. The ruleset version is surfaced (logged + in the `NewsScored` payload) so a re-score with a new ruleset is traceable.
6. Bounded-context rule holds: all event logic lives in `news` (reads `news`, writes `sentiment`); no `market_data` import. QV-046 will aggregate `sentiment.score` **and** `impact_score` into the sentiment factor.

## Tasks / Subtasks

- [x] **Task 1 — event taxonomy + impact config** (AC: #1, #2)
  - [x] `news/events.py`: `EventType` StrEnum (12 types); per-type keyword/phrase patterns (whole-word `\b…\b`, case-folded, dominant = max |weight|); `IMPACT_WEIGHTS` (signed, plan-scaled +30…−50); `IMPACT_RULESET_VERSION="impact-v1"`. Pure. Unit tests.
- [x] **Task 2 — EventImpactScorer** (AC: #3)
  - [x] `classify_event(text) -> EventType` + `EventImpactScorer.score(text, sentiment) -> Decimal` = `clamp(base + sentiment.score·25, −100, +100)`. Deterministic; NONE → pure-sentiment. Unit tests (dominance, modulation, clamp, conflict muted, fallback).
- [x] **Task 3 — persist impact in the sentiment pass** (AC: #4, #5)
  - [x] `upsert_sentiment` writes `impact_score`; `SentimentScoringService` takes an injected `EventImpactScorer` (default) and computes impact per article in the same pass; `impact_version` in the `NewsScored` payload + log. Integration test: persists, idempotent, EARNINGS_BEAT (+42.5) outranks REGULATORY (−27.5).
- [x] **Task 4 — gates + live + reconcile** (AC: #6)
  - [x] Gates green. Live dev re-score → **176/176 rows carry `impact_score`**, event-driven ("beats…raises"→+55, "NCLT insolvency"→−50, "acquires"→+45). QV-044 → done reconcile carried on this branch.

## Dev Notes

### Design (plan §1.4)
`EventImpactScorer.score(news, sentiment) -> float`, event type → impact (e.g. +25 contract win, −40 ban). Mirrors the QV-044 `DevSentiment` shape: a **pure, deterministic, versioned rules module** (`news/events.py`), applied inside `SentimentScoringService` so sentiment + impact are computed and persisted together (one pass, one row). The event classifier is keyword/rule-based (dev-grade, transparent) — a learned event model is a later increment, like FinBERT was for tone.

### Combine formula (impact-v1)
`impact_score = clamp(base_impact + sentiment.score · SENTIMENT_GAIN, −100, +100)`, `SENTIMENT_GAIN = Decimal(25)`. So: contract-win (+25) × positive tone (+1) → +50; ban (−40) × negative tone (−1) → −65; a **conflicting** signal (contract win but negative tone) mutes toward 0 (event still leads). `NONE` event (0 base) → pure-sentiment `score·25`, so tone-only articles still contribute modestly. All `Decimal` (money rule); `numeric(9,4)` holds the range.

### Where it lives / versioning
`impact_score` is written on the `sentiment` row (per `(news_id, model_version)`), so it inherits the sentiment model lineage; the **event ruleset** is independently versioned by the `IMPACT_RULESET_VERSION` constant (config = the editable `IMPACT_WEIGHTS`/patterns), surfaced in logs + the `NewsScored` payload. A per-row `impact_version` DB column is deferred (avoids a migration; add if audit needs it). Re-scoring with a new ruleset upserts in place (DO UPDATE).

### Not this story
- **Aggregating** per-stock sentiment + impact into the `SentimentFactor` → `scores.sentiment_score` → UI = **QV-046** (this only fills the per-article `impact_score`).
- Learned/zero-shot event classification; per-row impact-version column; provider event tags. Deferred.
- `news ⟂ market_data` contract must hold ([[sentiment-service-architecture]]).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Gates: ruff + format clean · mypy clean (189 files) · import-linter 3/3 (`news ⟂ market_data` holds) · pytest **399 passed / 5 skipped** (+11 event-impact unit tests + 1 impact integration assertion).
- Live dev re-score (`dev-lexicon-v1`, real corpus): **176/176 rows carry `impact_score`**. Samples — "Levi Strauss **beats**… **raises** guidance" +55, "Ola Electric… **NCLT insolvency**" −50, "Aastha Spintex **acquires** Falcon Yarns" +45.

### Completion Notes List

- **Computed in the QV-044 pass, not a second scan:** `EventImpactScorer` is injected into `SentimentScoringService`; each article's impact is derived from its event type × the just-computed sentiment and written on the same `sentiment` row. One pass, one row, idempotent per `(news_id, model_version)`. **No migration** — used the existing 0007 `impact_score` column.
- **Combine formula (impact-v1):** `clamp(base_impact + sentiment.score·25, −100, +100)`. Event leads; tone modulates; a conflicting signal (positive event, negative tone) mutes toward 0; a `NONE` event yields a pure-sentiment `score·25`.
- **Versioning:** `IMPACT_RULESET_VERSION="impact-v1"` (the editable `IMPACT_WEIGHTS`/patterns are the "config"); surfaced in the `NewsScored` payload + logs. A per-row `impact_version` DB column is deferred (no migration) — add if audit needs to distinguish rulesets per row.
- **Known dev-grade limitation:** keyword matching is headline-level, not entity-aware, so a macro headline ("China **bans** helium exports") can trip an event on a tagged stock's feed. Acceptable for dev; entity-aware event attribution / a learned classifier is a later increment (as FinBERT is for tone).
- Surfacing per-stock sentiment+impact into `scores.sentiment_score`/UI is **QV-046** (this only fills per-article `impact_score`).

### File List

- `backend/src/quantvista/news/events.py` (new) — `EventType`, `IMPACT_WEIGHTS`, `classify_event`, `EventImpactScorer`, `IMPACT_RULESET_VERSION`
- `backend/src/quantvista/news/repositories.py` — `upsert_sentiment` writes `impact_score`
- `backend/src/quantvista/news/services.py` — `SentimentScoringService` computes + persists impact; `impact_version` in event/log
- `backend/tests/test_event_impact.py` (new) — classifier + scorer unit tests
- `backend/tests/integration/test_sentiment_scoring.py` — impact-persistence assertion + `NewsScored` payload updated

### Change Log

- QV-045: Event-impact scorer — pure versioned event classifier (`news/events.py`, 12-type taxonomy + signed `IMPACT_WEIGHTS`, `impact-v1`) combined with QV-044 sentiment into a bounded `impact_score`, persisted on the `sentiment` row in the same scoring pass (no migration), `impact_version` surfaced in `NewsScored`. Aggregation into the score/UI is QV-046.

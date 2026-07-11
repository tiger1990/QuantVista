---
baseline_commit: 6e59ce7a706947bed9167779d5c7490815c345a4
---

Status: review

# QV-044 — FinBERT sentiment service + model runtime

**Epic:** EPIC-NEWS (Epic 5) · **Points:** 8 · **Depends:** QV-041 (news ingest ✓), QV-042 (tagging ✓)

## Story

As the platform, I want financial-news sentiment computed and stored as a reusable feature, so news becomes a quantified factor (QV-046) without any downstream consumer ever loading an NLP model.

## Acceptance Criteria

1. A `SentimentModel` seam classifies text into **positive / negative / neutral** with a signed **score** and a **confidence**, served **batched** on a dedicated **`nlp`** Celery queue.
2. Two interchangeable implementations behind the seam, selected by config (`SENTIMENT_MODEL=dev|finbert`):
   - **`DevSentiment`** (always-on, default) — deterministic financial **lexicon**; runs on any machine (your Mac x86/macOS-12/py3.13 + CI). `model_version="dev-lexicon-v1"`.
   - **`FinBERTSentiment`** — `ProsusAI/finbert` via `transformers`+`torch`, **lazy-imported** behind an optional **`[finbert]`** extra; runs on a capable machine (teammate box / Docker / EC2 / CI-Linux). `model_version="finbert-prosusai-v1"`.
3. The existing **`sentiment`** table (migration 0007 — `label/score/confidence/impact_score/model_version`, `UNIQUE(news_id, model_version)`) persists results. **Idempotent per news batch**; the two `model_version`s coexist per article (dev + finbert). **No migration.**
4. Scoring emits **`NewsScored(news_batch, count)`** after commit (durable-state announce, no phantom events).
5. **FinBERT is verified for real** (not just mocked) on Linux — a `@pytest.mark.finbert` test runs the actual model, exercised by a dedicated CI job that installs `.[finbert]`, and runnable on the teammate's machine.
6. Downstream (QV-046 factor, screener) will read **precomputed** rows from `sentiment` — the scoring seam is the only thing that touches a model.

## Tasks / Subtasks

- [x] **Task 1 — seam + DTOs** (AC: #1)
  - [x] `SentimentResult` DTO in `news/models.py` (label `Literal[…]`, `score`/`confidence` Decimal). Evolved the **published** `ISentimentService` (contract-tested by name in `test_import_skeleton`) into the batched seam — `model_version` + `classify(texts) -> Sequence[SentimentResult]` — rather than adding a new `SentimentModel` name; nothing implemented the old `score(text)->float`.
- [x] **Task 2 — DevSentiment (lexicon, always-on)** (AC: #2)
  - [x] `news/sentiment.py`: `DevSentiment` — curated financial pos/neg term sets; `score=(pos−neg)/(pos+neg)` (0 → neutral), label by sign, `confidence` by matched-term density. Pure, deterministic. 7 unit tests.
- [x] **Task 3 — FinBERTSentiment (optional extra, lazy)** (AC: #2, #5)
  - [x] `news/adapters/finbert.py`: lazy `transformers`/`torch`; `ProsusAI/finbert` pipeline; batched `classify`; `score = P(pos) − P(neg)`, `confidence = max prob`. Clear RuntimeError without the extra. `[finbert]` extra + mypy override in `pyproject.toml`.
  - [x] Fake-pipeline unit tests (no torch) + real `@pytest.mark.finbert` smoke test (auto-skips without torch).
- [x] **Task 4 — scoring service + repo** (AC: #3, #4)
  - [x] `news/repositories.py`: `iter_unscored_news` + `upsert_sentiment` (`ON CONFLICT (news_id, model_version) DO UPDATE`).
  - [x] `news/services.py`: `SentimentScoringService.score_unscored` — read → classify in batches → upsert → publish `NewsScored` after commit. Integration test (real Postgres, unique model_version per test for isolation): persist, idempotent, dev+finbert coexist, event emitted.
- [x] **Task 5 — Celery `nlp` queue + job + config** (AC: #1, #2)
  - [x] `jobs/sentiment.py`: `score_news` task; routed to the **`nlp`** queue via `task_routes`; `get_sentiment_model(settings)` factory (`dev`/`finbert`); `run_job` idempotent per bucket; off-beat + manually triggerable. `Settings.sentiment_model="dev"`; module registered in `celery_app` include. Factory + routing tests.
- [x] **Task 6 — CI finbert job + gates + reconcile** (AC: #5, #6)
  - [x] `backend-finbert` CI job (Linux) installs `.[dev,finbert]` + runs `-m finbert`, HF-weight cached, **non-blocking** (not in `ci-success` needs). Gates green. QV-095 → done reconcile carried on this branch.

## Dev Notes

### The scalable runtime (what the user approved)
FinBERT runs as a **Celery worker on the `nlp` queue** — any capable machine (`pip install .[finbert]` + `SENTIMENT_MODEL=finbert` + `celery -A quantvista.jobs.celery_app worker -Q nlp`) drains the same broker/DB and writes `finbert-prosusai-v1` rows. Your Mac + CI run the `default` queue with `DevSentiment` (`dev-lexicon-v1`). Both write the **same `sentiment` table**, distinguished by `model_version`; downstream reads **precomputed** scores (BlackRock-style separation-of-concerns) using infra we already own — **no new HTTP service, no k8s, no model registry** (pretrained model → no training pipeline; `model_version` gives audit/re-score).

```
your Mac (default queue)              teammate / Docker / EC2 / CI-Linux (nlp queue)
  DevSentiment (lexicon)                FinBERTSentiment (torch+transformers)
        └───────────────┬───────────────────────┘
                sentiment table (…, model_version)  UNIQUE(news_id, model_version)
                        └── QV-046 SentimentFactor → composite → screener
```

### Why this shape is forced here
No `torch`/`onnxruntime`/`tensorflow` wheel exists for **x86_64 macOS 12 + py3.13** (verified via `pip install --dry-run`); `transformers` installs but has no inference backend. So live FinBERT can't run on this box — authored + mock-tested here, **real-run verified on Linux (CI + teammate)**. Mirrors [[aws-infra-deferred]] / [[native-install-before-deferral]] / [[kafka-local-feasibility]]: real adapter built now, live-run on a capable host.

### Idempotency & events
`sentiment` has `UNIQUE(news_id, model_version)`. `score_unscored` only reads news lacking a row for the active `model_version`, then upserts — safe to re-run, and a re-score (model bump) is a new `model_version`. `NewsScored` fires **after** the commit (same discipline as `FactorsComputed`/`ScoresComputed` in `jobs/scoring.py`). Follow the `run_job`/`JobRunLedger`/`run_key` framework and the `NewsIngestionService` publish pattern.

### Lexicon model (dev)
Small curated financial sentiment lists (gains/beats/sur9e/upgrade/contract-win vs. probe/ban/default/downgrade/fraud…), matched on `headline + " " + summary`, case-folded, word-boundary. `score=(pos−neg)/(pos+neg)`; label: `>+t → positive`, `<−t → negative`, else `neutral`; `confidence = min(1, (pos+neg)/K)`. Deterministic (golden tests). Money/scores stay `Decimal` (`Decimal(str(...))`).

### Not this story / fast-follow
- **Provider-sentiment passthrough** (Marketaux returns per-article sentiment, [[news-provider-strategy]]) — the `news` table doesn't persist it today, so passthrough needs a `news.provider_sentiment` column + QV-041 adapter plumbing. Deferred (documented) to keep QV-044 migration-free; DevSentiment stays lexicon-only for now.
- **Event-impact score** (`impact_score` column) = QV-045. **Sentiment factor into composite** = QV-046. Live FinBERT rollout on a capable host = a PV item (like PV-002 for AWS).
- Bounded-context rule: sentiment scoring lives entirely in `news` (reads `news`, writes `sentiment`); it must NOT import `market_data` — the `news ⟂ market_data` contract holds. QV-046 (analytics) reads `sentiment`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Live dev run (`SENTIMENT_MODEL=dev`, real news corpus, 176 articles): `score_unscored` → **176 scored**; distribution neutral 128 / positive 40 / negative 8. Correctly caught cues — "Levi Strauss **beats**… **raises** guidance" → positive, "Sensex **Jumps** 800 Points" → positive. `NewsScored` emitted.
- Gates: ruff clean · mypy clean (187 files) · import-linter 3/3 (`news ⟂ market_data` holds) · pytest **388 passed / 5 skipped** (+18 sentiment tests; the real-finbert test skips without torch).

### Completion Notes List

- **Naming:** kept the published `ISentimentService` (architecture contract, `test_import_skeleton`) as the seam and evolved it from `score(text)->float` to the batched `classify(texts)->Sequence[SentimentResult]` — no separate `SentimentModel` type. Both `DevSentiment` and `FinBERTSentiment` satisfy it structurally.
- **No migration:** the `sentiment` table (0007) already had `label/score/confidence/impact_score/model_version` + `UNIQUE(news_id, model_version)`. Idempotency and dev↔finbert coexistence fall straight out of that unique key.
- **FinBERT deferral confirmed empirically:** `pip install --dry-run torch onnxruntime` → no wheel for x86_64 macOS 12 + py3.13. Real-run verified via the non-blocking Linux CI job (`backend-finbert`) + the teammate's machine; the dev box runs `DevSentiment`.
- **Test-isolation gotcha (fixed):** `score_unscored` scans ALL unscored news (no universe filter), so the integration test must use a **unique model_version per test** and clean up by it — a first non-isolated version polluted the dev DB with 352 fake rows (had to `DELETE FROM sentiment` and re-score for real). Assertions are count-independent.
- **Provider-sentiment passthrough** deferred (documented): the `news` table doesn't persist provider sentiment, so it needs a `news` column + QV-041 adapter plumbing. DevSentiment is lexicon-only for now.

### File List

- `backend/src/quantvista/news/models.py` — `SentimentResult`, `SentimentLabel`, `UnscoredArticle`, `SentimentReport`
- `backend/src/quantvista/news/interfaces.py` — `ISentimentService` evolved into the batched seam
- `backend/src/quantvista/news/sentiment.py` (new) — `DevSentiment` lexicon model
- `backend/src/quantvista/news/adapters/finbert.py` (new) + `adapters/__init__.py` — `FinBERTSentiment` (lazy, optional)
- `backend/src/quantvista/news/repositories.py` — `iter_unscored_news`, `upsert_sentiment`
- `backend/src/quantvista/news/services.py` — `SentimentScoringService`
- `backend/src/quantvista/jobs/sentiment.py` (new) — `score_news` task + `get_sentiment_model` factory
- `backend/src/quantvista/jobs/celery_app.py` — `nlp` queue route + include; `backend/src/quantvista/core/config.py` — `sentiment_model`
- `backend/pyproject.toml` — `[finbert]` extra, mypy overrides, `finbert` pytest marker, jobs untyped-decorator entry
- `.github/workflows/ci.yml` — non-blocking `backend-finbert` job
- `backend/tests/test_sentiment_lexicon.py`, `test_finbert_adapter.py`, `test_sentiment_job.py` (new); `tests/integration/test_sentiment_scoring.py` (new)

### Change Log

- QV-044: FinBERT sentiment service + model runtime — pluggable `ISentimentService` seam (DevSentiment lexicon always-on; FinBERTSentiment via the `[finbert]` extra), `score_news` on a dedicated `nlp` Celery queue, writes the existing `sentiment` table keyed by `model_version` (idempotent, dev+finbert coexist), emits `NewsScored`. FinBERT real-run deferred off x86 macOS 12 → verified in a non-blocking CI-Linux job. No migration.

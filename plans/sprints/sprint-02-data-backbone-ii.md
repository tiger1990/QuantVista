# Sprint 02 — Data Backbone II (Bitemporal Fundamentals & Indicators)

**Phase:** 1 · **Goal:** point-in-time fundamentals + ownership data, technical indicators, and the in-process
event bus that drives the pipeline DAG.
**Exit gate:** bitemporal fundamentals stored; indicators computed on `PricesIngested`; correction handling
re-opens versions and re-triggers downstream.

> See `../03-data-architecture.md` §5 (PIT), `../06-scheduler-and-jobs.md` (event DAG).

---

### QV-021 — Schema: fundamentals (bitemporal) `[DATA]` · `8pts` · Epic: EPIC-DATA · depends: QV-013
**Story:** As the analytics layer, I want point-in-time-correct fundamentals, so scores/backtests have no
look-ahead bias.
**Acceptance criteria:**
- `fundamentals` with `period_end`, `reported_at`, `knowledge_from/knowledge_to`; all ratios as `NUMERIC`.
- A revision inserts a new version and closes the prior `knowledge_to`; nothing destructively updated.
- Repository exposes `as_of(date)` returning the row valid at `date`.
**Notes:** `03` §5 — the credibility backbone.

### QV-022 — `ingest_fundamentals` (versioned upsert) `[DATA]` · `5pts` · Epic: EPIC-DATA · depends: QV-021, QV-012
**Story:** As the platform, I want fundamentals ingested with correction handling, so restatements are
captured truthfully.
**Acceptance criteria:**
- Ingests latest filings; new/revised data creates a bitemporal version; idempotent on re-run.
- Emits `FundamentalsUpdated`.
**Notes:** Late corrections trigger re-scoring (`06` §5).

### QV-023 — Schema + `ingest_shareholding` (PIT ownership) `[DATA]` · `3pts` · Epic: EPIC-DATA · depends: QV-013, QV-012
**Story:** As the analytics layer, I want promoter/FII/DII/public holding over time, so ownership factors work.
**Acceptance criteria:**
- `shareholding` keyed `(stock_id, as_of_date)`; quarterly ingest + poll; `pledged_pct` captured.
**Notes:** India-specific factors kept market-scoped (`future-us-market-expansion.md`).

### QV-024 — In-process event bus (`IEventBus`) `[BE]` · `5pts` · Epic: EPIC-DATA · depends: QV-015
**Story:** As the platform, I want domain events decoupling producers/consumers, so the pipeline is a DAG and
later extractable to Redis Streams.
**Acceptance criteria:**
- `IEventBus.publish/subscribe`; events `PricesIngested`, `FundamentalsUpdated`, `IndicatorsComputed`,
  `FactorsComputed`, `ScoresComputed`, `NewsScored` defined with typed payloads.
- Handlers run in-process now; interface identical to a future stream consumer (`02` §7).
**Notes:** Seam for `future-scale-microservices.md`.

### QV-025 — Schema: technical_indicators (partitioned) + `compute_indicators` `[QUANT]` · `8pts` · Epic: EPIC-DATA · depends: QV-014, QV-017, QV-024
**Story:** As the analytics layer, I want technical indicators computed daily, so momentum/risk factors have
inputs.
**Acceptance criteria:**
- Compute SMA/EMA, RSI-14, MACD, Bollinger, ATR-14, 3/6/12M returns, 30d vol, 1y beta using **adjusted**
  prices; partitioned monthly.
- Triggered by `PricesIngested`; idempotent per `(market, date)`; emits `IndicatorsComputed`.
- Polars-vectorized; full universe completes well under the freshness SLO.
**Notes:** `03` §4.1, `06` §3.

### QV-026 — `sync_macro_series` (rates/inflation/GDP) `[DATA]` · `3pts` · Epic: EPIC-DATA · depends: QV-015
**Story:** As the analytics layer, I want macro time series, so macro context is available to factors/ML.
**Acceptance criteria:**
- Generic `macro_series` table; ingest from FRED (+ RBI/MOSPI where public); idempotent.
**Notes:** `03` §4.1.

### QV-027 — Correction-handling pipeline test `[QUANT]` · `3pts` · Epic: EPIC-DATA · depends: QV-022, QV-025
**Story:** As QA, I want proof that data corrections self-heal, so revisions don't leave stale derived data.
**Acceptance criteria:**
- Test: ingest fundamentals → revise → assert new bitemporal version + downstream recompute enqueued for
  affected dates.
**Notes:** `06` §5.

**Sprint total:** ~38 pts · **Dependency note:** unblocks Sprint 03 (scoring needs indicators + PIT
fundamentals + event bus).

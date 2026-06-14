# Sprint 01 — Data Backbone I (Prices & Ingestion)

**Phase:** 1 · **Goal:** stand up the provider abstraction and ingest EOD prices + corporate actions for the
Nifty 200 universe, idempotently and observably.
**Exit gate:** `ingest_daily_prices` runs idempotently for the full Nifty 200, recorded in `jobs_runs`,
with data-quality gates passing.

> See `../03-data-architecture.md` (schema, partitioning), `../06-scheduler-and-jobs.md` (jobs).

---

### QV-012 — `IMarketDataProvider` interface + dev adapter `[DATA]` · `5pts` · Epic: EPIC-DATA · depends: QV-001
**Story:** As the platform, I want all market data behind one interface, so vendors swap without analytics
changes.
**Acceptance criteria:**
- `IMarketDataProvider` defines `get_prices`, `get_corporate_actions`, `get_fundamentals`, `get_shareholding`,
  `list_universe`.
- A dev adapter (yfinance/public, **internal-only**) implements it; provenance fields populated
  (`source`, `source_url`, `license_class='non_commercial_dev'`).
**Notes:** This abstraction is *why* O2 is deferrable (`03` §1).

### QV-013 — Schema: stocks, markets, index_constituents, corporate_actions `[DATA]` · `5pts` · Epic: EPIC-DATA · depends: QV-004
**Story:** As the platform, I want the reference/master schema, so prices and analytics have anchors.
**Acceptance criteria:**
- Alembic migrations for `stocks` (incl. `delisted_on`, `isin`), `index_constituents` (PIT membership),
  `corporate_actions`; unique/indexes per `03` §4.1.
- These are **global** tables (no `tenant_id`, no RLS).
**Notes:** `delisted_on` + PIT constituents are mandatory for survivorship-free history (`03` §5).

### QV-014 — Schema: daily_prices (monthly range partitions) `[DATA]` · `5pts` · Epic: EPIC-DATA · depends: QV-013
**Story:** As the platform, I want partitioned price storage, so time-series scale and pruning work.
**Acceptance criteria:**
- `daily_prices` range-partitioned by month on `date`; btree `(stock_id, date)` + BRIN on `date`; unique
  `(stock_id, date)`.
- Partition auto-creation for new months automated.
**Notes:** `03` §6.

### QV-015 — Job framework: idempotency + `jobs_runs` + Celery/Beat wiring `[BE]` · `5pts` · Epic: EPIC-DATA · depends: QV-002
**Story:** As an operator, I want every job idempotent and recorded, so retries are safe and runs auditable.
**Acceptance criteria:**
- Job base computes a `run_key`; writes start/finish/rows/status/error to `jobs_runs`.
- Celery broker/result (Redis) + Beat singleton configured; a sample scheduled task runs end to end.
**Notes:** `06` §1–§2.

### QV-016 — `ingest_daily_prices` (idempotent, full universe) `[DATA]` · `8pts` · Epic: EPIC-DATA · depends: QV-012, QV-014, QV-015
**Story:** As the platform, I want daily EOD prices for Nifty 200, so analytics has its core input.
**Acceptance criteria:**
- Ingests OHLCV for all active constituents; upsert keyed `(stock_id, date)`; re-run = no duplicates.
- Per-stock failure isolated; aggregate report; emits `PricesIngested` event.
**Notes:** `06` job catalog.

### QV-017 — `ingest_corporate_actions` + adjusted-close computation `[DATA]` · `5pts` · Epic: EPIC-DATA · depends: QV-016
**Story:** As the analytics layer, I want corporate-action-adjusted prices, so splits/bonuses don't fake
momentum.
**Acceptance criteria:**
- Ingest splits/bonuses/dividends; compute `adj_close` from raw `close` + actions; raw retained.
- Recompute is idempotent on re-ingest of late actions.
**Notes:** Feeds momentum factors & backtests (`05` §4).

### QV-018 — Data-quality gates (post-ingestion) `[DATA]` · `5pts` · Epic: EPIC-DATA · depends: QV-016
**Story:** As an operator, I want ingestion validated before downstream use, so we never score on bad data.
**Acceptance criteria:**
- Gates: row count vs expected universe size, null-rate thresholds, price sanity (no ≤0), gap checks.
- A failing gate halts downstream and alerts (does not silently proceed).
**Notes:** `06` §5.

### QV-019 — `sync_stock_master` + `sync_index_constituents` `[DATA]` · `3pts` · Epic: EPIC-DATA · depends: QV-013
**Story:** As the platform, I want master + index membership kept current, so the universe stays correct.
**Acceptance criteria:**
- Weekly master sync; constituents sync on reconstitution with PIT `effective_from/to` + weights.
- Emits `StockMasterUpdated` / `ConstituentsUpdated`.
**Notes:** `06` job catalog.

### QV-020 — Job observability dashboard `[PLAT]` · `3pts` · Epic: EPIC-PLAT · depends: QV-009, QV-015
**Story:** As an operator, I want job health visible, so failures surface fast.
**Acceptance criteria:**
- Grafana panels: queue depth, task latency p50/p95, failure rate, **freshness lag** (now − latest price
  date); alert on DLQ non-empty / freshness breach.
**Notes:** `08` §6–§7.

**Sprint total:** ~49 pts · **Dependency note:** unblocks Sprint 02 (fundamentals/indicators).

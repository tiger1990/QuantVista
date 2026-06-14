# 06 — Scheduler & Job Orchestration

> Celery + Redis (broker/result) + Celery Beat (schedule). All jobs **idempotent, replayable, observable**.

---

## 1. Principles

1. **Idempotent & keyed.** Every run computes a `run_key` (e.g., `prices:NSE:2026-06-13`). Re-running with the
   same key upserts, never duplicates. Recorded in `jobs_runs` (see `03`).
2. **Pipeline as a DAG, not a cron soup.** Downstream jobs are triggered by **domain events**
   (`PricesIngested → indicators → factors → scores → ScoresComputed → alerts/cache invalidation`), not by
   guessing timing. Beat only kicks the *roots* of each DAG.
3. **Backfill = same code, different window.** Historical backfill uses the same tasks parameterized by date
   range. No separate "loader scripts" that drift from production logic.
4. **Fail loud, retry smart.** Exponential backoff with jitter; dead-letter on exhaustion; alert on repeated
   failure. Partial failure of one stock never blocks the universe (per-stock isolation + aggregate report).
5. **Correctness over speed.** Late data corrections re-open bitemporal rows (`03` §5); a correction triggers
   re-scoring for affected dates.

---

## 2. Job catalog

| Job | Cadence (IST) | Trigger | Idempotency key | Emits |
|-----|---------------|---------|-----------------|-------|
| `sync_stock_master` | Weekly + on demand | Beat | `master:{market}:{week}` | `StockMasterUpdated` |
| `sync_index_constituents` | On NSE reconstitution + monthly check | Beat | `constituents:{index}:{date}` | `ConstituentsUpdated` |
| `ingest_daily_prices` | Post-close (~18:30) | Beat | `prices:{market}:{date}` | `PricesIngested` |
| `ingest_corporate_actions` | Daily | Beat | `corpact:{market}:{date}` | `CorpActionsUpdated` |
| `ingest_fundamentals` | On filing / daily poll | Beat | `fund:{stock}:{period}:{rev}` | `FundamentalsUpdated` |
| `ingest_shareholding` | Quarterly + poll | Beat | `shp:{stock}:{quarter}` | — |
| `compute_indicators` | After `PricesIngested` | Event | `ind:{market}:{date}` | `IndicatorsComputed` |
| `compute_factors` | After indicators+fundamentals | Event | `fac:{market}:{date}` | `FactorsComputed` |
| `compute_scores` | After factors+sentiment | Event | `score:{universe}:{date}` | `ScoresComputed` |
| `ingest_news` | Hourly | Beat | `news:{window}` | `NewsIngested` |
| `score_sentiment` | After `NewsIngested` | Event | `sent:{news_batch}` | `NewsScored` |
| `evaluate_alerts` | After `ScoresComputed` / `NewsScored` | Event | `alerts:{date}:{trigger}` | `AlertsFired` |
| `invalidate_caches` | After `ScoresComputed` | Event | n/a | — |
| `run_backtest` | On demand (user) | API | `bt:{backtest_id}` | `BacktestFinished` |
| `run_optimization` | On demand (user) | API | `opt:{run_id}` | `OptimizationFinished` |
| `sync_macro_series` | Daily/weekly | Beat | `macro:{series}:{date}` | — |
| `retrain_models` | Monthly | Beat | `train:{model}:{month}` | `ModelPromoted?` |
| `send_digests` | Daily/weekly | Beat | `digest:{tenant}:{date}` | — |
| `reconcile_billing` | Daily | Beat | `billing:{date}` | — |

---

## 3. Daily pipeline (happy path)

```
18:30  ingest_daily_prices ─emit─▶ PricesIngested
                                     └▶ compute_indicators ─▶ IndicatorsComputed
(parallel) ingest_corporate_actions ─▶ (adj_close recompute)
(async)    ingest_fundamentals ─▶ FundamentalsUpdated
                                     └▶ compute_factors (needs indicators+fundamentals)
hourly     ingest_news ─▶ score_sentiment ─▶ NewsScored
                                     └▶ compute_scores (factors + latest sentiment)
                                          └▶ ScoresComputed
                                               ├▶ invalidate_caches
                                               └▶ evaluate_alerts ─▶ AlertsFired ─▶ notifications
```

**SLO:** scores for date `D` ready before next market open (09:15 IST `D+1`). Alarm if not.

---

## 4. Queues, workers, concurrency

- **Queues by class:** `ingest`, `compute`, `nlp` (FinBERT — GPU/CPU-heavy), `user` (backtests/optimization —
  interactive), `notify`. Separate queues prevent a long backtest from starving price ingestion.
- **Worker pools:** autoscaled on queue depth (KEDA on K8s — see `08`). `nlp` workers sized for the model
  runtime. `user` queue has **per-tenant concurrency caps** so one tenant can't monopolize backtest capacity
  (noisy-neighbor control from `02`).
- **Celery Beat** runs as a **singleton** (leader-elected) to avoid duplicate scheduling.
- **Time limits & soft limits** per task; backtests get longer budgets and stream progress to `backtests`.

---

## 5. Reliability & correctness mechanisms

- **Exactly-once-ish via idempotency keys** (Celery is at-least-once; idempotent upserts make retries safe).
- **Dead-letter queue** + automatic alert after N failures; runbook links in alert payload.
- **Data-quality gates:** after ingestion, validate row counts vs expected universe size, null-rate
  thresholds, and price sanity (no negative/zero, gap checks). Failing a gate halts downstream and alerts
  rather than scoring on bad data.
- **Correction handling:** a fundamentals revision inserts a new bitemporal version and enqueues
  `compute_factors`/`compute_scores` for affected dates → scores self-heal.
- **Tenant context in user jobs:** backtest/optimization tasks set `app.tenant_id` so RLS applies; global
  data jobs run under the privileged role limited to reference tables.

---

## 6. Observability of jobs (ties to `08`)

- Every task: structured logs with `run_key`, duration, rows in/out, outcome → `jobs_runs` + metrics.
- Dashboards: queue depth, task latency p50/p95, failure rate, freshness lag (now − latest `scores.date`).
- Alerts: pipeline freshness SLO breach, DLQ non-empty, data-quality gate failure, vendor `upstream_unavailable`.

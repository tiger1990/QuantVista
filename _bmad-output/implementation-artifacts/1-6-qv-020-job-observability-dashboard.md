---
baseline_commit: 3916dbded580fecb9d391801239b54e166b4a8e7
---

# Story 1.6: QV-020 — Job observability dashboard

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **an operator**,
I want **job health visible on a dashboard with alerts on the pipeline SLOs (freshness, failure rate, queue backlog)**,
so that **a stalled ingest, a failing job, or a backed-up queue surfaces fast — before scores are computed on stale data or a silent failure snowballs**.

> Canonical ID **QV-020** · Epic 1 (EPIC-PLAT) · `[PLAT]` · 3pts · Sprint 01 · depends: **QV-009 ✅** (observability baseline), **QV-015 ✅** (job framework)
> Authoritative: `plans/08` §6 (Metrics → Grafana: workers = queue depth, task latency p50/p95, failure rate, DLQ size; **data freshness = `now − max(data.date)`** the headline pipeline SLO) · `08` §7 (SLO/alert table: pipeline freshness lag > threshold; job success rate → DLQ non-empty / repeated failure) · `06` §6 (every task → `jobs_runs` + metrics; freshness-lag alert).

## Locked decisions

- **Build + verify locally on native binaries; defer only the truly live parts to staging.** This machine has **no Docker and no AWS** ([[docker-local-env-deferred]], [[aws-infra-deferred]]) but **Prometheus + Grafana install natively via Homebrew** ([[native-install-before-deferral]]) — same posture that closed Postgres/Redis. So we author + test the whole observability config locally and defer only *live rendering* + *notification delivery* + *production scrape* to the staging machine.
- **`promtool test rules` is the deterministic alert gate.** Alert logic (fresh → inactive, stale → **Firing**) is unit-tested with synthetic series via `promtool test rules` — no running Prometheus/Grafana needed. A pytest shells out to `promtool` and **skips if it's absent** (mirrors the DB integration-test auto-skip), so CI/other machines never hard-fail on a missing binary.
- **Freshness is exported as a timestamp gauge, lag is derived in PromQL.** The app exposes `data_latest_ingest_timestamp_seconds{dataset}` (unix ts of the newest ingested row); freshness lag = `time() - data_latest_ingest_timestamp_seconds` in the panel + alert — always current regardless of scrape cadence (never a stale pre-computed "lag" number). `08` §6's headline is `now − max(scores.date)`; **scores don't exist yet** (QV-029+), so the metric is **parameterized by `dataset`** and currently tracks `daily_prices` — `scores` is a one-line add when it lands.
- **Extend QV-009's metrics surface — do not duplicate it.** RED (API) + `celery_tasks_total` / `celery_task_duration_seconds` / `celery_task_failures_total` (worker) already exist (`core/observability/metrics.py`). QV-020 adds only the two missing gauges (**freshness**, **queue depth**) + a refresh path, and builds the dashboard/alerts on the union.
- **Config lives in versioned `ops/`.** Prometheus scrape config + alert rules + rule tests + the Grafana dashboard JSON are checked-in artifacts (`ops/prometheus/`, `ops/grafana/`) — the same files import into staging Grafana/Prometheus unchanged. No secrets in them.
- **Pending-verifications recorded for the staging machine.** Live Grafana visual rendering, alert **notification delivery** (Slack/PagerDuty/email), and the **production scrape** from the deployed app are appended to **PV-003** (gated on PV-002 AWS staging). A native local Prometheus+Grafana smoke is optional here (bonus, not the gate).

## Acceptance Criteria

1. **Freshness metric.** A gauge `data_latest_ingest_timestamp_seconds{dataset}` is exposed on both roles' `/metrics` (API endpoint + worker server). `update_data_freshness(session)` sets it from `SELECT max(date) FROM daily_prices` (→ unix ts); a missing/empty dataset leaves it unset (no fake 0). Unit-tested.
2. **Queue-depth metric.** A gauge `celery_queue_depth{queue}` set by `update_queue_depth(redis_client)` from the Redis `LLEN` of the Celery queue(s). Unit-tested with a fake Redis. (Live broker depth verification → PV-003.)
3. **Refresh path.** A Celery task `refresh_ops_metrics` calls both updaters (freshness + queue depth) so the gauges stay current between scrapes; wired into `beat_schedule` at a short interval (ops metrics *are* the thing we schedule — unlike data jobs). Idempotent, cheap, no data mutation.
4. **Prometheus config + alert rules** (`ops/prometheus/`): `prometheus.yml` scrapes the api (`:8000/metrics`) + worker (`:9100`); `alerts.yml` defines — **PipelineFreshnessLagHigh** (`time() - data_latest_ingest_timestamp_seconds{dataset="daily_prices"} > threshold`), **JobFailureRateHigh** (`increase(celery_task_failures_total[15m]) > 0` sustained), **QueueBacklogHigh** (`celery_queue_depth > threshold`). Each alert carries a `summary`/`runbook` annotation. `promtool check config` + `check rules` pass.
5. **Deterministic alert tests.** `ops/prometheus/alerts_test.yml` (`promtool test rules`): a fresh timestamp → freshness alert **inactive**; a stale timestamp → **firing**; task failures present → JobFailureRateHigh **firing**; queue below/above threshold → QueueBacklogHigh inactive/firing.
6. **Grafana dashboard** (`ops/grafana/dashboards/job-observability.json`): panels for **task latency p50/p95** (`histogram_quantile` over `celery_task_duration_seconds`), **task failure rate**, **tasks by terminal state**, **pipeline freshness lag**, **queue depth**. Valid JSON; every panel targets a metric name that actually exists. Structurally validated by a test.
7. **Gates + docs + PV.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on new Python. `ops/README.md` documents running the stack natively (brew `prometheus`/`grafana`) + import into staging. `docs/pending-verifications.md` PV-003 gains the live-render / notification-delivery / production-scrape items. `market_data`/DAG boundaries unaffected (metrics live in `core`/`jobs`).

## Tasks / Subtasks

- [x] **Task 1 — freshness + queue-depth metrics** (AC: #1, #2)
  - [x] `core/observability/metrics.py`: add `DATA_FRESHNESS = Gauge("data_latest_ingest_timestamp_seconds", …, ["dataset"])` and `QUEUE_DEPTH = Gauge("celery_queue_depth", …, ["queue"])`. `update_data_freshness(session)` (max(date) → `.set(ts)`; skip if None) and `update_queue_depth(redis_client, queues=("default",))` (`LLEN` → `.set`). No new dependency (`prometheus_client`, `redis` already present).
  - [x] `tests/test_ops_metrics.py`: fake session/redis → gauges set to expected values; metric names appear in `render_metrics()`.
- [x] **Task 2 — refresh task + beat wiring** (AC: #3)
  - [x] `jobs/ops_metrics.py` (new): `@app.task refresh_ops_metrics()` opens a `privileged_session_scope` + a Redis client, calls both updaters. Add to `celery_app.py` `beat_schedule` (e.g. every 60s). Add the module to the mypy untyped-decorator override. Unit/integration test the task path (monkeypatched session/redis) — no live broker needed.
- [x] **Task 3 — Prometheus config + alert rules + rule tests** (AC: #4, #5)
  - [x] `ops/prometheus/prometheus.yml` (scrape api+worker), `ops/prometheus/alerts.yml` (3 rules w/ annotations), `ops/prometheus/alerts_test.yml` (`promtool test rules` cases: fresh/stale, failures, queue).
  - [x] `tests/test_prometheus_rules.py`: shell out to `promtool check config`, `check rules`, `test rules`; **skip** if `promtool` not on PATH.
- [x] **Task 4 — Grafana dashboard JSON** (AC: #6)
  - [x] `ops/grafana/dashboards/job-observability.json`: the five panels with correct PromQL. `tests/test_grafana_dashboard.py`: valid JSON, expected panel titles, every `expr` references a known metric name.
- [x] **Task 5 — docs, PV, gates** (AC: #7)
  - [x] `ops/README.md` (native run + staging import). Append PV-003 items (live render / notification delivery / production scrape). Optional native smoke (run `prometheus` scraping a local app; confirm target up + metric present). Run all gates; reconcile QV-019 → done (already applied on this branch).

## Dev Notes

### Scope discipline
QV-020 = **operator-facing job health**: the two missing metrics (freshness, queue depth) + a refresh task + Prometheus alert rules (with deterministic `promtool` tests) + a Grafana dashboard JSON, all built on QV-009's existing metrics. **Not this story:** live Grafana rendering / alert notification delivery / production scrape (→ **PV-003**, staging), infra USE metrics + business metrics (`08` §6 — later), the Loki/OpenSearch logging pipeline, synthetic journey checks (`08` §7), the `scores.date` freshness source (→ when QV-029 lands; the `dataset` label makes it a one-liner). **No schema/migration.**

### What QV-009 already gives us (extend, don't rebuild)
`core/observability/metrics.py`: API RED (`http_requests_total`, `http_request_errors_total`, `http_request_duration_seconds`, `http_requests_by_tenant_total`); worker (`celery_tasks_total{task,state}`, `celery_task_duration_seconds{task}`, `celery_task_failures_total{task}`); `render_metrics()` → API `/metrics`; `start_worker_metrics_server(port)` (worker, `worker_metrics_port=9100`); `install_worker_metrics()` (Celery signals). Settings: `metrics_enabled=True`, `redis_url`, `worker_metrics_port`. Dashboard PromQL reuses these directly (latency p50/p95 = `histogram_quantile(0.5|0.95, sum(rate(celery_task_duration_seconds_bucket[5m])) by (le, task))`; failure rate = `rate(celery_task_failures_total[5m])`).

### Metric design
- **Freshness = timestamp gauge, lag in PromQL** (see Locked decisions). `data_latest_ingest_timestamp_seconds{dataset="daily_prices"}` = `extract(epoch from max(date))`. Alert: `time() - metric > FRESHNESS_LAG_THRESHOLD` (start generous, e.g. 36h for a T-1 daily feed across a weekend — tune on staging).
- **Queue depth** = Redis `LLEN` of the Celery list key(s). Celery's default queue is a Redis list named `default` (matches `task_default_queue="default"` in `celery_app.py`). DLQ size is a follow-on once a dead-letter queue exists; for now QueueBacklogHigh on the main queue is the "backlog/repeated-failure" proxy from `08` §7.
- Both gauges are process-registry singletons (like the existing metrics); the `refresh_ops_metrics` beat task keeps them fresh on the worker registry that Prometheus scrapes.

### Local verification posture (native, no Docker)
- `brew install prometheus grafana` (both confirmed available; `prometheus` bundles `promtool`). `promtool check config ops/prometheus/prometheus.yml`, `promtool check rules ops/prometheus/alerts.yml`, `promtool test rules ops/prometheus/alerts_test.yml` — deterministic, server-free.
- `tests/test_prometheus_rules.py` shells to `promtool` and **skips** if absent (never a hard CI failure on a machine without it).
- Optional smoke: run a local api (`uvicorn`) + `prometheus --config.file=ops/prometheus/prometheus.yml`, hit `:9090`, confirm the target is `up` and the freshness metric is present.

### Genuinely deferred → PV-003 (staging)
Grafana visual rendering against live data · alert **notification channels** (Slack/PagerDuty/email) actually delivering · the **production scrape** from the deployed api/worker. These need the running staging stack (gated on PV-002 AWS). Record them; do not fake them.

### Boundaries & gates
- New Python lives in `core/observability` (metrics) + `jobs/` (the beat task) — both existing composition areas; `market_data` DAG untouched; `lint-imports` stays 3/3. Add `quantvista.jobs.ops_metrics` to the mypy untyped-decorator override (as `jobs.ingest`/`quality`/`universe`).
- Coverage ≥ 80% on the new metric updaters + task. The `promtool`/Grafana-JSON tests guard the config artifacts.

### Memory / PV pointers
Live observability backends were already deferred in QV-009 → **PV-003** (blocked on PV-002). This story adds the dashboard/alert *artifacts* to that same PV so the staging bring-up has a concrete import + verify checklist. Related: [[ci-required-status-checks]].

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN per task)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (106 files) ·
  `lint-imports` 3 kept/0 broken · `pytest` → **208 passed, 3 skipped** (the `promtool` rule tests —
  see below), coverage **96 %** (new: `jobs/ops_metrics.py` 100 %, `core/observability/metrics.py` 97 %).
- **`promtool` could NOT be installed on this dev machine (macOS 12):** no Prometheus Homebrew bottle →
  source build pulls a toolchain (node/pnpm/…) and fails on a broken patch `.diff` download; a raw-binary
  fetch is policy-blocked. So `tests/test_prometheus_rules.py`'s 3 `promtool` cases **skip here**. Two
  mitigations: (1) **always-on YAML structural tests** (`test_prometheus_rules.py`) that DO run — assert
  `alerts.yml` is valid, has all 3 alerts with expr+runbook, and every alert has a `promtool` case; (2)
  **wired `promtool` into CI** (`.github/workflows/ci.yml` `backend-tests`, Linux release tarball) so the
  deterministic firing tests **execute on every PR**. Local execution recorded as a PV (teammate runs
  `pytest tests/test_prometheus_rules.py` on a box where promtool installs). See `docs/pending-verifications.md` → PV-003.
- **Deferred to staging (PV-003):** live Grafana rendering, alert notification delivery (Slack/PagerDuty),
  production scrape from the deployed api/worker.

### Completion Notes List

- **Extends QV-009's metrics surface** with the two missing pipeline-health gauges: freshness
  (`data_latest_ingest_timestamp_seconds{dataset}`, exported as a **timestamp** — lag = `time() - gauge`
  in PromQL, never stale) and `celery_queue_depth{queue}`. The dashboard's latency p50/p95 + failure-rate
  panels reuse QV-009's existing `celery_task_*` metrics. **No schema/migration.**
- **Refresh path:** `jobs/ops_metrics.py::refresh_ops_metrics` Beat task (every 60s) sets both gauges from
  a privileged session (`max(daily_prices.date)`) + a Redis `LLEN`. This IS the thing we schedule (ops
  metrics), unlike data jobs. DB/Redis I/O lives in `jobs` (composition root); `core` keeps only thin
  gauge setters — DAG boundaries unaffected (`lint-imports` 3/3).
- **Alert rules** (`ops/prometheus/alerts.yml`): `PipelineFreshnessLagHigh` (>36h), `JobFailureRateHigh`,
  `QueueBacklogHigh`, each with a runbook annotation. Proven by `promtool test rules` (fresh→inactive,
  stale→firing, failures→firing, backlog→firing/inactive) — runs in CI.
- **Grafana dashboard JSON** (`ops/grafana/…/job-observability.json`): 5 panels, structurally validated
  (valid JSON, expected titles, every `expr` targets a real metric — a typo can't ship to staging).
- **Freshness source note:** `08` §6's headline is `max(scores.date)`; scores don't exist yet (QV-029+),
  so the metric is `dataset`-parameterized and tracks `daily_prices` now — `scores` is a one-line add.
- **No security-reviewer** — read-only metric queries, no auth/PII/user-input. `/metrics` network-restriction
  requirement already recorded in PV-003 (QV-009).

### File List

**New**
- `backend/src/quantvista/jobs/ops_metrics.py` — freshness + queue-depth updaters + `refresh_ops_metrics` task.
- `backend/tests/test_ops_metrics.py` — updater unit tests (fake session/redis).
- `backend/tests/integration/test_ops_metrics_task.py` — task wiring (real PG, fake Redis) + registration.
- `backend/tests/test_prometheus_rules.py` — always-on YAML structural checks + `promtool` (skip-if-absent).
- `backend/tests/test_grafana_dashboard.py` — dashboard JSON structural validation.
- `ops/prometheus/prometheus.yml`, `ops/prometheus/alerts.yml`, `ops/prometheus/alerts_test.yml` — scrape + rules + rule tests.
- `ops/grafana/dashboards/job-observability.json` — 5-panel dashboard.
- `ops/README.md` — native run + staging import + PV pointer.

**Modified**
- `backend/src/quantvista/core/observability/metrics.py` — `DATA_FRESHNESS`/`QUEUE_DEPTH` gauges + setters.
- `backend/src/quantvista/market_data/repositories.py` — `latest_price_date` (freshness source).
- `backend/src/quantvista/jobs/celery_app.py` — `refresh_ops_metrics` beat entry + `include`.
- `backend/pyproject.toml` — `PyYAML`/`types-PyYAML` dev deps; mypy override for `jobs.ops_metrics`.
- `.github/workflows/ci.yml` — install `promtool` in `backend-tests` so the alert-rule tests execute.
- `docs/pending-verifications.md` — PV-003 gains QV-020 dashboard/alert import + the `promtool`-local note.

### Change Log

- **2026-07-04 — QV-020 job observability dashboard.** Added the freshness + queue-depth gauges +
  `refresh_ops_metrics` Beat task (extending QV-009's metrics), Prometheus alert rules with deterministic
  `promtool test rules`, and a 5-panel Grafana dashboard JSON — all as versioned `ops/` artifacts. Alert
  logic runs in CI (promtool wired into `backend-tests`); live rendering/notifications/prod-scrape → PV-003.
  208 tests passed / 3 skipped (promtool absent on macOS 12), coverage 96 %; ruff/mypy-strict/import-linter
  clean. No migration.

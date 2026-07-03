# ops/ — observability config (QV-020)

Checked-in Prometheus + Grafana artifacts for job/pipeline health. The **same files** import into
staging Grafana/Prometheus unchanged (only scrape targets differ). No secrets live here.

```
ops/
├── prometheus/
│   ├── prometheus.yml     # scrape config (api :8000/metrics, worker :9100)
│   ├── alerts.yml         # PipelineFreshnessLagHigh · JobFailureRateHigh · QueueBacklogHigh
│   └── alerts_test.yml    # promtool test rules — deterministic alert-logic proof
└── grafana/
    └── dashboards/
        └── job-observability.json   # 5 panels: latency p50/p95, failure rate, tasks by state,
                                      # freshness lag, queue depth
```

## Metrics this consumes

From QV-009 (`core/observability/metrics.py`): `celery_tasks_total{task,state}`,
`celery_task_duration_seconds{task}`, `celery_task_failures_total{task}`.
Added by QV-020: `data_latest_ingest_timestamp_seconds{dataset}` (freshness — lag is
`time() - metric`, derived in PromQL) and `celery_queue_depth{queue}`. Both are refreshed by the
`refresh_ops_metrics` Beat task (every 60s).

## Verify locally (native, no Docker)

```bash
brew install prometheus grafana          # prometheus bundles promtool

# Static + deterministic (no server needed) — also run by pytest:
promtool check config ops/prometheus/prometheus.yml
promtool check rules  ops/prometheus/alerts.yml
promtool test  rules  ops/prometheus/alerts_test.yml   # asserts fresh→ok, stale→firing, etc.

# Optional live smoke:
uvicorn quantvista.api.app:app --port 8000            # exposes /metrics
prometheus --config.file=ops/prometheus/prometheus.yml # scrapes it; open http://localhost:9090
```

The pytest suite runs the `promtool` checks automatically and **skips** them if `promtool` isn't
installed (so CI/other machines never hard-fail).

## Deferred to staging (PV-003)

Live Grafana rendering against real data, alert **notification delivery** (Slack/PagerDuty/email),
and the **production scrape** from the deployed api/worker — these need the running staging stack
(gated on PV-002 AWS). See `docs/pending-verifications.md` → PV-003 for the import + verify checklist.

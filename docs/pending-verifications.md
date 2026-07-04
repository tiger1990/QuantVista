# Pending Verifications (verification debt)

Living ledger of work that has been **merged on accepted risk** because some verification step
could not be completed in the implementing environment. Each item names *what* is unverified, *why*,
*how* to verify, and the **hard gate** by which it must be closed.

> Review this list at the start of every sprint and before any story listed as a blocking gate.

## Two kinds of deferral — don't confuse them

This ledger tracks **only one** of the two ways work gets pushed to "later". Know which is which:

- 🔧 **Environment/verification debt → belongs HERE (PV-*).** The code is *written and offline-checked*;
  only the "run it on real infra and confirm" step is blocked because this machine lacks the environment
  (no Docker engine on macOS 12 → PV-001; no AWS account/creds → PV-002/PV-003). **Fix:** run the PV's
  runbook later on a capable machine. Development elsewhere does **not** wait on it.

- 🧭 **Deliberate scope deferral → does NOT belong here.** The code simply isn't built yet because it was
  *intentionally scheduled into a future story* (e.g. the prod `JWT_SECRET` startup guard → **QV-079**
  hardening pass). It is not blocked by any machine and is tracked in the **story backlog / sprint**,
  not this ledger. **Fix:** implement it when that story comes up.

Rule of thumb: if a *different machine* would let you close it, it's a PV. If it just needs *someone to
write the code* (any machine), it's a backlog story — put it in the epic/sprint, not here.

| ID | Item | Why deferred | How to verify | Gate (must close before) | Status |
|----|------|--------------|---------------|--------------------------|--------|
| PV-001 | **QV-002 container stack** — live `docker compose up` smoke test (AC #1–3: all services healthy, `GET /api/v1/health` → 200 envelope, web on :3000, seed loaded, worker/beat ready, **images build**) | Primary dev machine (macOS 12 Monterey, Intel) cannot run any Docker engine — Colima/Lima need QEMU (Homebrew won't build it on Monterey, Tier-3) and Docker Desktop is unsupported on macOS 12. Static checks all pass (`docker compose config` valid; backend + frontend gates green). | On a Docker-capable machine: `git checkout master`, `cp .env.example .env`, `docker compose up --build`; confirm all services healthy, `curl localhost:8000/api/v1/health` → 200, `curl localhost:3000` → 200, `worker`/`beat` logs ready, spot-check a seeded reference row. | **Before the container images are relied on** — i.e. before staging/CD (QV-008 IaC / QV-084 CD). **No longer gates QV-004** (see note). | ⏳ OPEN |
| PV-002 | **QV-008 AWS staging infra** — live Terraform rollout: bootstrap `apply` → backend `init` → `workspace new staging` → `plan` → human review → `apply` → **confirm staging reachable**. Offline checks (`fmt -check`, `init -backend=false`, `validate`, `tflint`) are done **in** QV-008; this row covers only the steps that create real cloud resources. | Dev environment has **no AWS account/credentials**. EKS control plane + multi-AZ RDS + ElastiCache + NAT gateways accrue hourly cost and are slow/irreversible to destroy — an agent must **not** create them unattended. D8 "no click-ops" intent applies equally as "no robo-ops": a human runs the rollout. | On a credentialed machine (AWS account, Terraform-capable IAM/OIDC role, Terraform ≥ 1.6, AWS CLI v2, `kubectl`), follow the runbook in `infra/terraform/README.md` — ordered steps mirrored in Notes below. Green = `kubectl get nodes` reaches the EKS cluster, RDS/Redis private endpoints resolve from in-cluster, app/parquet S3 buckets exist, Secrets Manager entries populated, env outputs captured. | **Before anything relies on a live staging env** — QV-009 (observability stack) and QV-084 (CD / deploy to staging); and necessarily **before any production environment** is stood up from the same workspace-ready code. | ⏳ OPEN (also blocked on QV-008 Terraform being authored) |
| PV-004 | **QV-015 job framework — live Celery worker + Beat + Redis run.** The framework (run_key + `JobRunLedger` + `run_job` + `sample_scheduled_job` + `beat_schedule`) built in QV-015. **Native-broker portion VERIFIED locally (2026-07-03):** installed `redis` via Homebrew (8.x, Monterey Intel), ran `celery ... worker` against native Redis + native Postgres, enqueued `sample_scheduled_job.delay()` → worker consumed → `jobs_runs` row `status='succeeded'` (rows recorded, `finished_at` set); a same-key re-run → `skipped` (idempotency holds over the real broker); `celery ... beat` starts and loads the `sample-heartbeat` schedule. Only the **containerized** variant remains. | The native worker/Beat/Redis stack **runs fine here** (Redis installs natively — it was never truly blocked, just not installed; see memory). What is NOT verifiable here is the **container** variant (image build + compose service wiring) — that belongs to PV-001 (Docker won't run on Monterey). | Native path (done): `brew install redis`; `redis-server --daemonize yes`; `celery -A quantvista.jobs.celery_app worker` + `... beat`; enqueue + confirm `jobs_runs`. Container path (remaining): via the PV-001 container stack (`docker compose up redis worker beat`). | **Before QV-016 ingestion relies on Beat-scheduled jobs in the *container/staging* env.** Native local run satisfied; container run folded into **PV-001**. | ✅ CLOSED (native, 2026-07-03); container variant → PV-001 |
| PV-003 | **QV-009 observability — live staging backends.** The in-app instrumentation (structlog JSON, OpenTelemetry tracing, Prometheus `/metrics` + RED/worker metrics, env-gated Sentry) is **built + offline-tested in QV-009**. This row covers only the "**wired in staging**" clause (`plans/08 §6`): point the running api/worker at a real OTLP collector (Tempo/Jaeger), a Grafana instance with operator dashboards, and a Sentry project, then confirm traces, metrics, logs, and errors actually land end-to-end. **Deploy requirement:** `/metrics` (api) and the worker metrics port carry a `tenant` label (tenant UUIDs) and are unauthenticated at the app layer — they MUST be network-restricted to the Prometheus scraper (private subnet / NetworkPolicy / not internet-routable), never publicly exposed. | No live staging env and **no credentials** in the implementing environment (blocked on **PV-002**). There is no collector, Grafana, or Sentry project to point at; the endpoints/DSN are supplied via Secrets Manager at deploy time, not in dev. | On live staging (after PV-002): set `OTEL_EXPORTER_OTLP_ENDPOINT`, `SENTRY_DSN`, `LOG_JSON=true` via Secrets Manager/env; deploy api+worker; generate traffic (login, `/api/v1/health`, run a Celery task) + force one error; verify — Prometheus scrapes `/metrics` (api) + the worker port, traces appear in Grafana Tempo/Jaeger, JSON logs carry `request_id`/`trace_id`, the forced error lands in Sentry; confirm `/metrics` is unreachable from the public internet; then build the operator dashboards (pipeline health, API RED, tenant usage, cost) from `plans/08 §6`. | **Before QV-020** (job-observability dashboard) and **QV-082** (SLOs & alerting) rely on live telemetry. Itself **blocked on PV-002** (staging must exist first). | ⏳ OPEN (blocked on PV-002) |
| PV-005 | **QV-016 initial 5-year price backfill** — a one-off operational run of `backfill_daily_prices` to load ~5y of daily OHLCV for the current universe into `daily_prices`. **Also:** the daily `ingest_daily_prices` job is **not** in `beat_schedule` yet — wire its cadence (post-close ~18:30 IST) when a live scheduler runs (staging / PV-004). | **Deliberate operational deferral, NOT environment-blocked** (unlike PV-001/002/003 — this *runs fine here* on native Postgres + Yahoo, proven live for one session). Deferred by choice: it loads ~15k non-commercial dev rows (Yahoo, rate-limit-sensitive) and the *authoritative* history load belongs with the licensed vendor / staging, so we hold it until analytics needs the history. | Run once: `python -c "from datetime import date, timedelta; from quantvista.jobs.ingest import backfill_daily_prices; backfill_daily_prices('NSE', start=date.today()-timedelta(days=365*5), end=date.today()-timedelta(days=1))"` (needs `pip install -e .[dev-data]` for yfinance). Green = `jobs_runs` row `succeeded` + `SELECT count(*) FROM daily_prices` reflects ~5y × universe. Then add `ingest_daily_prices` to `beat_schedule` for the daily cadence. | **Before the first story that needs real price *history*** — backtesting / factor-scoring (Epic 4+) and **QV-020** (job dashboard shows a real pipeline). Not a blocker for QV-017/018 (which can use a short window). | ⏳ OPEN (operational; runnable here on demand) |

## Notes

- **PV-001 decoupled from QV-004 (2026-06-20):** QV-004 needs *a* Postgres, not the *container
  stack*. The dev machine has a local **PostgreSQL 18.4** (Homebrew `postgresql@18`) on
  `localhost:5432`; the `quantvista` DB + non-superuser `quantvista_app` role are provisioned,
  migrations `0001`→`0012` apply, and RLS isolation was verified manually. So QV-004 proceeds against
  the local Postgres. PV-001 now only verifies the **Docker images + compose wiring** (Dockerfiles
  build, services network, `migrate`/`seed` one-shots, `web` serves) — which matters before those
  images are promoted to staging.
- **PV-001:** if the live run surfaces a bug (e.g. Celery `-A` discovery, the `migrate`/`seed`
  ordering, the Next.js standalone build, or the `quantvista_app` grants), fix it as a follow-up on
  a `fix/qv-002-*` branch — do not block QV-004 planning, but it must be green before QV-004 code
  lands. Detail: `_bmad-output/implementation-artifacts/1-2-qv-002-local-dev-environment-docker-compose.md`
  and `plans/sprints/sprint-00-foundations.md` (QV-002 deferred-verification note).

### PV-002 — what QV-008 delivers vs. what is deferred

- **Delivered in QV-008 (offline, in-repo, CI-gated):** the full staging Terraform under
  `infra/terraform/` (VPC, EKS, RDS Postgres, ElastiCache Redis, S3, IAM/IRSA, Secrets Manager) on
  registry modules, remote-state `bootstrap/`, per-env **workspace**-ready env composition, and the
  offline quality gate (`terraform fmt -check -recursive`, `init -backend=false` + `validate`,
  `tflint`) wired into a paths-filtered `infra` CI job. **No cloud resources are created.**
- **Deferred to a credentialed human (this PV):** every step that touches real AWS — bootstrap
  apply, backend init against the S3 bucket, workspace create, `plan`, `apply`, and the
  "staging reachable" check. Region **`ap-south-1`** (D8). Secret values are **generated**
  (`random_password`) into Secrets Manager — never committed — so there is nothing secret to leak in
  the deferral.

### PV-002 — prerequisites before any live run

- A dedicated **AWS account** (recommend separate accounts, or at minimum separate workspaces, for
  `staging` vs `production`).
- A Terraform-capable **IAM principal / OIDC role** (create VPC/EKS/RDS/ElastiCache/S3/IAM/Secrets).
- **Terraform ≥ 1.6**, **AWS CLI v2**, **kubectl**, credentials loaded (`aws sso login` or env keys).

### PV-002 — ordered bring-up runbook (the steps to complete later)

1. **Bootstrap remote state** (once per account): `cd infra/terraform/bootstrap && terraform init &&
   terraform apply` → S3 state bucket (versioned, encrypted, public-access-blocked) + DynamoDB lock
   table. Record the output names.
2. **Wire the backend:** confirm `envs/staging/backend.tf` points at the bootstrap bucket/table
   (`key` includes the workspace).
3. **Init the env:** `cd ../envs/staging && terraform init` (s3 backend).
4. **Create/select workspace:** `terraform workspace new staging` (then `select staging`).
5. **Plan + human review:** `terraform plan -var-file=staging.tfvars` — scrutinise IAM scope, SG
   ingress (no `0.0.0.0/0` to RDS/Redis), public-access blocks, encryption.
6. **Apply:** `terraform apply -var-file=staging.tfvars` — provisions the stack.
7. **Capture outputs:** VPC id, EKS cluster name/endpoint, RDS endpoint, Redis endpoint, bucket names
   (no secret values).
8. **Confirm reachable:** `aws eks update-kubeconfig --region ap-south-1 --name <cluster>` →
   `kubectl get nodes`; confirm RDS/Redis **private** endpoints resolve from in-cluster; verify
   Secrets Manager entries are populated.
9. **Close PV-002:** set ✅ CLOSED (date + account), check the QV-008 live subtask, and remove the
   gate from QV-009 / QV-084.

### PV-002 — additional steps required specifically before PRODUCTION (beyond staging)

- New **`production` workspace** (isolated state) + `production.tfvars`: larger sizing, **multi-AZ
  on**, RDS **deletion protection** + automated backups + PITR, longer retention.
- **CloudFront + WAF**, production DNS + TLS cert, stricter least-privilege IAM; ideally a
  **separate AWS account** from staging.
- Re-run **`security-reviewer`** on the production composition; confirm KMS keys, encryption in
  transit + at rest everywhere, and **Secrets Manager rotation** enabled.
- **Config/secret alignment:** Terraform outputs + Secrets Manager keys must match the env var names
  the app reads — `DATABASE_URL`, `ADMIN_DATABASE_URL`, `REDIS_URL`, `S3_*`, `JWT_SECRET`
  (`backend/src/quantvista/core/config.py`) — so QV-084 CD can inject them unchanged.

### PV-002 — if a live `apply` surfaces a problem

Fix it forward on a `fix/qv-008-*` branch (the IaC analogue of the migrations rule — all infra
change via reviewed PR; remote state + DynamoDB lock prevent concurrent/clobbering applies). Keep
PV-002 ⏳ OPEN until the rollout is clean and re-verified. Detail:
`_bmad-output/implementation-artifacts/1-4-qv-008-iac-bootstrap-aws-staging.md`.

### PV-003 — QV-020 dashboard & alert artifacts to import on staging

QV-020 builds the job-observability artifacts **locally** (no longer fully gated on PV-003 — only the
*live* clauses below are). Built + verified here: the freshness gauge (`data_latest_ingest_timestamp_seconds`)
+ queue-depth gauge (`celery_queue_depth`) on `/metrics`, the `refresh_ops_metrics` Beat task, the
Prometheus scrape config + alert rules (`ops/prometheus/`, structurally gated by an always-on YAML test),
and the Grafana dashboard JSON (`ops/grafana/dashboards/job-observability.json`, structurally validated).

> **PV — `promtool test rules` execution.** The deterministic alert-logic proof (fresh→ok, stale→firing,
> failures→firing, backlog→firing) runs via `promtool`, which **could not be installed on the dev machine**
> (macOS 12 has no Prometheus bottle → Homebrew source-build pulls a broken patch; a raw-binary download is
> policy-blocked). **Now gated in CI** — `.github/workflows/ci.yml` `backend-tests` installs `promtool`
> (Linux release tarball) so `tests/test_prometheus_rules.py` **executes on every PR**. The pytest cases
> `skip` where `promtool` is absent, so a **teammate can run them locally**: `brew install prometheus`
> (or download the release tarball), then `cd backend && pytest tests/test_prometheus_rules.py` — expect
> `check config` + `check rules` + `test rules` all green. Status: ✅ CI-gated; ⏳ local dev-machine run
> pending a box where promtool installs.

What still needs the running staging stack (add to the PV-003 verify run):

1. **Import the dashboard** (`ops/grafana/dashboards/job-observability.json`) into staging Grafana; confirm
   all five panels render against live scraped data (task latency p50/p95, failure rate, tasks by state,
   freshness lag, queue depth).
2. **Load the alert rules** (`ops/prometheus/alerts.yml`) into staging Prometheus; confirm they evaluate
   and that `PipelineFreshnessLagHigh` / `JobFailureRateHigh` / `QueueBacklogHigh` transition to **Firing**
   under real stale-data / failure / backlog conditions.
3. **Notification delivery:** wire Alertmanager → the real channel (Slack/PagerDuty/email) and confirm a
   firing alert actually delivers with its runbook annotation.
4. **Production scrape:** confirm Prometheus scrapes the deployed api (`/metrics`) + worker port and the
   freshness/queue gauges reflect the live pipeline.

## How to close an item

1. Run the verification on a capable machine.
2. If green: set Status to ✅ CLOSED (date + machine), check the corresponding story subtask, and
   remove the gate from any blocked story.
3. If red: open a `fix/*` branch, link it here, keep Status ⏳ OPEN until merged + re-verified.

## Deferred data sources (🧭 scope deferrals — fast-follow stories, NOT verification debt)

Per the taxonomy above these are **scope** deferrals (code not written yet), not PV env-debt — logged
here only for **visibility at sprint review** so we don't lose track of what macro coverage remains.
They become their own backlog stories (own QV numbers) behind the existing `IMacroProvider` seam
(`market_data/macro.py`) — each is a drop-in adapter + a `MacroSeries`→provider-code map; **no core change.**

QV-026 shipped **FRED** (US/global, fresh) + **World Bank** (India + cross-country, *annual*, current-year).
The gap is **monthly/daily fresh Indian** macro, which neither FRED nor World Bank provides:

| Deferred source | Serves (fresh) | Why not now | Effort |
|-----------------|----------------|-------------|--------|
| **RBI** (Reserve Bank of India / DBIE) | Repo & reverse-repo, CRR/SLR, G-sec yields, USD/INR, forex reserves, M1/M2/M3 — **daily/weekly** | No single FRED-like REST API; per-dataset endpoints/downloads → provider-specific adapter work | Medium–High |
| **MOSPI** (Min. of Statistics) | **CPI monthly** (~12th), IIP monthly, GDP quarterly, national accounts | Distributed as CSV/Excel/PDF; Unitdata API needs registration + key | Medium–High |
| **IMF** | Cross-country inflation, fiscal balance, public debt, current account | Lower priority — World Bank already covers cross-country annual | Low–Medium |

**Gate:** before the factor/scoring layer (Epic 4+) needs *timely monthly* Indian macro (e.g. live CPI
momentum), stand up the **MOSPI** (monthly CPI/IIP) and **RBI** (rates/yields/FX) adapters. Until then,
World Bank annual India + FRED US/global is the accepted coverage. Roadmap detail in the
`macro-provider-strategy` memory.

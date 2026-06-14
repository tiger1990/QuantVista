# 08 — Infrastructure, DevOps & Observability

> Docker (local + CI), Kubernetes (prod), Terraform IaC, GitHub Actions CI/CD, environments, monitoring,
> logging, SLOs. Cloud target = AWS by default (O1); IaC keeps it portable.

---

## 1. Environments

| Env | Purpose | Data | Notes |
|-----|---------|------|-------|
| `local` | Dev | seed + synthetic | docker-compose; MinIO for S3; one Postgres/Redis |
| `ci` | Tests | ephemeral | spun per pipeline; teardown after |
| `staging` | Pre-prod, vendor sandbox | prod-like, anonymized | mirrors prod topology; smoke + E2E |
| `production` | Live | licensed data, real tenants | multi-AZ, backups, alerting |

Config is env-driven (`pydantic-settings`); secrets from AWS Secrets Manager/SSM. Promotion is image-based:
the **same image** built once flows local→staging→prod with config differences only.

---

## 2. Containerization

- **Multi-stage Dockerfiles**, non-root user, pinned base images, minimal runtime layers.
- One backend image runs three roles via command (`api` / `worker` / `beat`) — single artifact, single
  build, no logic drift (per `02`).
- **docker-compose (local):** `postgres`, `redis`, `minio`, `api`, `worker`, `beat`, `web`, `nginx`,
  optional `finbert` model server. Network `quantvista-net`; volumes `pg_data`, `redis_data`, `minio_data`.
- Frontend built as static/SSR Next.js image; served via CDN + Node runtime for ISR.

---

## 3. Kubernetes (production)

- **Deployments:** `web`, `api` (HPA on CPU + RPS), `worker` (autoscaled by **queue depth via KEDA**),
  `beat` (singleton, leader-elected), optional `finbert` (own pool, CPU/GPU sized).
- **Managed services (not in-cluster):** PostgreSQL (RDS/Aurora, multi-AZ, read replica), Redis
  (ElastiCache), object store (S3). Reduces ops load (funded team, but lean ops is still smart).
- **Ingress:** ALB/NGINX ingress → `api`; CDN (CloudFront) → `web`. TLS via ACM/cert-manager.
- **Resilience:** PodDisruptionBudgets, liveness/readiness probes, requests/limits, multi-AZ node groups.
- **Secrets:** External Secrets Operator → Secrets Manager. **NetworkPolicies** restrict pod-to-pod traffic.

> Microservice extraction (splitting modules into separate deployments) is deferred to
> `future-scale-microservices.md`; the seams in `02` make it incremental.

---

## 4. Infrastructure as Code

- **Terraform** for all cloud resources (VPC, EKS, RDS, ElastiCache, S3, IAM, Secrets, CloudFront, WAF),
  remote state + locking, per-env workspaces. No click-ops in prod.
- Kubernetes manifests via **Helm** (or Kustomize) per env. GitOps (Argo CD) optional once stable.

---

## 5. CI/CD (GitHub Actions)

**Git strategy:** trunk-ish — `main` (deployable) + short-lived `feature/*`; protected `main`, required
reviews + green checks. (A `develop` branch optional if the team prefers GitFlow.)

**Pipeline stages:**
```
PR:  lint (Ruff) ─ typecheck (mypy) ─ unit tests ─ RLS/authz tests ─ bias regression tests
     ─ frontend lint+typecheck+unit ─ build ─ SAST + secret scan + SCA (pip-audit)
main merge:  build & push image (scanned by Trivy) ─ DB migration check
     ─ deploy staging ─ integration + E2E (Playwright) + smoke
     ─ manual approval ─ deploy production (rolling) ─ post-deploy smoke + freshness check
```
- **Migrations** run as a gated step (expand/contract, never destructive in one release — see `03`/
  `database-migrations`).
- **Coverage gate** ≥ 80% (per testing rules). Backtest **bias regression tests** are mandatory and
  non-skippable.
- **Rollback:** image rollback + migration-compatible (backward-compatible) deploys; documented runbook.

---

## 6. Observability

- **Tracing:** OpenTelemetry across `api`/`worker`; trace IDs in logs & responses (`meta.request_id`).
- **Metrics (Prometheus → Grafana):**
  - API: RED (Rate, Errors, Duration) per route; per-tenant request volume.
  - Workers: queue depth, task latency p50/p95, failure rate, DLQ size.
  - **Data freshness:** `now − max(scores.date)` — the headline pipeline SLO metric.
  - Infra: USE (Utilization, Saturation, Errors) for nodes/DB/Redis.
  - Business: signups, conversions, active sessions, backtests run.
- **Logging:** structured JSON (structlog) → Loki or OpenSearch/Kibana; correlation via request/trace IDs;
  PII-aware redaction.
- **Error tracking:** Sentry (backend + frontend).
- **Dashboards:** built to answer operator questions (pipeline health, API health, tenant usage, cost), not
  vanity boards.

---

## 7. SLOs & alerting

| SLO | Target | Alert on |
|-----|--------|----------|
| API availability | 99.5% (→99.9%) | error-budget burn rate |
| API read latency p95 | < 300 ms | sustained breach |
| Pipeline freshness | scores ready before 09:15 IST | lag > threshold |
| Job success rate | > 99% | DLQ non-empty / repeated failure |
| Data-quality gates | 100% pass before scoring | any gate failure |

Alerts route to on-call (PagerDuty/Opsgenie) with runbook links; noisy alerts pruned. Synthetic checks on
critical user journeys (login, view score, run screen).

---

## 8. Backups, DR, cost

- **Backups:** automated Postgres snapshots + PITR; object-store versioning; tested **restore drills**.
- **DR:** documented RPO/RTO; cross-AZ now, cross-region snapshots for later. Runbooks for region loss.
- **Cost controls:** Polars/Parquet to cut compute; autoscale-to-baseline off-hours; budget alerts; cache to
  cut DB load; right-sized model serving. Track cost-per-tenant to inform pricing (O3).

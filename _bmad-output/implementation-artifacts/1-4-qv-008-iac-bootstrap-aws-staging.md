---
baseline_commit: 8687d164d517965f99a272ab8cc74f959567ba7e
---

# Story 1.4: QV-008 — IaC bootstrap (AWS staging)

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the team**,
I want **reproducible AWS staging infrastructure defined as Terraform** (VPC, EKS, RDS Postgres, ElastiCache Redis, S3, IAM, Secrets Manager in `ap-south-1`) **with remote state + locking and per-env workspaces**,
so that **environments are stood up and changed through reviewed code, never click-ops**.

> Canonical ID **QV-008** · Epic 1 (EPIC-PLAT) · `[PLAT]` · 8pts · Sprint 00 · depends: **—**
> Authoritative detail: `plans/sprints/sprint-00-foundations.md` §QV-008. Infra: `plans/08-infra-devops-observability.md` §1–4. Locked decision **D8** (AWS `ap-south-1`, Terraform, portable).

## ⚠️ Read this first — execution boundary (CRITICAL)

This story is **authoring + offline validation of Terraform**, not a live cloud rollout.

- **DO NOT run `terraform apply`, `terraform import`, or anything that creates/modifies real AWS resources.** EKS + RDS + ElastiCache in staging cost real money and are slow/irreversible to tear down, and provisioning needs an AWS account + credentials the dev environment does not have.
- The agent completes everything that is **offline-verifiable**: `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`, and `tflint` (no credentials, no network mutations).
- The live steps — `bootstrap` apply, `terraform workspace` create, `plan`/`apply` for staging, and **"staging reachable"** — are **deferred to a credentialed operator** and recorded as a new pending-verification **PV-002** (mirrors PV-001 for docker). See AC #7 + Task 7.
- This is outward-facing, hard-to-reverse, paid infrastructure: **a human runs `apply`.** Do not automate it.

## Acceptance Criteria

1. **Terraform authored for the full staging stack** in `infra/terraform/` (`ap-south-1`): **VPC** (multi-AZ public/private subnets, NAT), **EKS** (managed node group, multi-AZ), **RDS PostgreSQL** (multi-AZ-capable, storage-encrypted, in private subnets, not publicly accessible), **ElastiCache Redis** (private subnets, encryption in transit/at rest), **S3** (app/artifacts + parquet/exports buckets; SSE, versioning, public access blocked), **IAM** (least-privilege roles incl. an EKS IRSA/OIDC role for External Secrets), **Secrets Manager** (secret resources for DB/Redis credentials — values generated, never hard-coded).
2. **Remote state + locking** configured: an **S3 backend** (versioned, encrypted bucket) with **DynamoDB** state-lock table. Because the backend can't store its own creation, a separate **`bootstrap/`** config (local state) provisions the state bucket + lock table; the env config then uses the `s3` backend. Documented in the infra README.
3. **Per-env workspaces:** the staging env is parameterized so the **same code** serves future `staging`/`production` via Terraform **workspaces** (state isolated per workspace; resources name/tag-suffixed by workspace). `staging.tfvars` holds staging-specific sizing.
4. **Reuses battle-tested modules:** VPC/EKS/RDS/ElastiCache are built on the official **`terraform-aws-modules/*`** registry modules (pinned versions) — do not hand-roll networking, cluster, or DB primitives. Provider/Terraform versions pinned in `versions.tf`.
5. **Security & secrets hygiene:** no AWS keys, no secret values, no `*.tfstate`, no `*.tfvars` with secrets committed (gitignored). Encryption on: state bucket, all app S3 buckets, RDS storage, Redis. RDS/Redis **not** publicly reachable (private subnets + security groups). IAM is least-privilege. **`security-reviewer` runs on the IAM/Secrets/networking code** (DoD: sensitive paths).
6. **Offline validation green:** `terraform fmt -check -recursive`, `terraform init -backend=false` + `terraform validate` (each config), and `tflint` all pass locally and in CI. A **paths-filtered `infra` CI job** runs fmt/validate/tflint (offline only — **no** `plan`/`apply` in PR CI, which would need cloud creds).
7. **Live apply explicitly deferred (PV-002):** add a `PV-002` row to `docs/pending-verifications.md` capturing *what* is unverified (bootstrap apply → workspace `staging` → `plan`/`apply` → staging reachable), *why* (no AWS account/creds in the implementing environment), *how to verify* (the runbook in the infra README), and the *gate* (must close before QV-009 observability / QV-084 CD rely on staging). A human-run **runbook** for the live steps is in `infra/terraform/README.md`.

## Tasks / Subtasks

- [x] **Task 1 — Layout, versions, gitignore** (AC: #1,#4,#5)
  - [x] Create `infra/terraform/` with `versions.tf` (`required_version >= 1.6`, `required_providers { aws = "~> 5.0" }` — confirm current stable on the registry), `providers.tf` (`region = var.aws_region`, default tags), and a top-level `README.md` stub. **Deviation (documented in Completion Notes):** `versions.tf`/`providers.tf` live **per root module** (`bootstrap/`, `envs/staging/`), not as a non-functional top-level file (a top-level `provider` block with no resources fails `terraform validate`). Top-level holds `README.md` + `.gitignore`. Resolved AWS provider: **v5.100.0**.
  - [x] Add an `infra/terraform/.gitignore` (and/or extend root `.gitignore`): ignore `**/.terraform/`, `*.tfstate`, `*.tfstate.*`, `*.tfvars` **except** committed non-secret `*.tfvars` (commit `staging.tfvars` only if it holds no secrets), `crash.log`, `.terraform.lock.hcl` policy per team (commit the lock file — it pins module/provider hashes).
- [x] **Task 2 — Remote-state bootstrap** (AC: #2)
  - [x] `infra/terraform/bootstrap/` (local state): S3 state bucket (versioning on, SSE-S3/KMS, public access blocked, lifecycle for old versions) + DynamoDB lock table (`LockID` hash key, PAY_PER_REQUEST). Outputs: bucket name, table name. README: run this **once** before the env config.
- [x] **Task 3 — Reusable module wrappers** (AC: #1,#4)
  - [x] `infra/terraform/modules/network` → wrap `terraform-aws-modules/vpc/aws` `~> 5.13` (3 AZ, public+private subnets, single/HA NAT toggle, tags for EKS subnet discovery `kubernetes.io/role/*`).
  - [x] `infra/terraform/modules/eks` → wrap `terraform-aws-modules/eks/aws` `~> 20.24` (managed node group, OIDC/IRSA enabled, private endpoint + restricted public endpoint, cluster in private subnets).
  - [x] `infra/terraform/modules/rds` → wrap `terraform-aws-modules/rds/aws` `~> 6.10` (PostgreSQL 16, encrypted, private subnet group, SG allowing only EKS nodes, master password → Secrets Manager, multi-AZ flag var).
  - [x] `infra/terraform/modules/redis` → ElastiCache Redis (replication group, private subnet group, encryption in transit + at rest, SG from EKS only).
  - [x] `infra/terraform/modules/storage` → S3 buckets (app artifacts, parquet/exports) with SSE, versioning, public-access-block, ownership controls.
  - [x] `infra/terraform/modules/secrets` → Secrets Manager secrets (DB/Redis) + IAM: an IRSA role/policy for External Secrets Operator to read them (least privilege, scoped by ARN).
- [x] **Task 4 — Staging env composition + workspaces** (AC: #1,#3)
  - [x] `infra/terraform/envs/staging/` composes the modules; `backend.tf` declares the `s3` backend (bucket/table from bootstrap, workspace isolates state via `env:/<workspace>/`); `variables.tf` + `staging.tfvars` (region `ap-south-1`, sizes, AZ count); `outputs.tf` (VPC id, EKS cluster name/endpoint, RDS endpoint, Redis endpoint, bucket names — **no secret values**).
  - [x] Document the per-env workspace flow in README (`terraform workspace new staging` → `terraform workspace select staging`); resources carry a `${terraform.workspace}` name/tag suffix.
- [x] **Task 5 — CI: offline infra gate** (AC: #6)
  - [x] Extend `detect-changes` in `.github/workflows/ci.yml` with an `infra` filter (`infra/**`); add an `infra` job (gated on it) that runs `terraform fmt -check -recursive`, `terraform init -backend=false` + `terraform validate` per config, and `tflint`. **No** `plan`/`apply` (needs cloud creds). Wire the job into the `CI success` aggregator's `needs` so skips are handled like the frontend jobs.
- [x] **Task 6 — Offline validation** (AC: #6)
  - [x] Run locally: `terraform fmt -recursive`, `terraform init -backend=false && terraform validate` in `bootstrap/` and `envs/staging/`, and `tflint`. Fix all findings. Record exact commands + output in the Dev Agent Record. **Do not** run `plan`/`apply`. (All 8 configs green — see Debug Log.)
- [x] **Task 7 — Docs, runbook, PV-002, security review** (AC: #5,#7)
  - [x] `infra/terraform/README.md`: architecture overview, prerequisites (AWS account, OIDC/role, CLI), the **human runbook** for live bring-up (bootstrap apply → backend init → `workspace new staging` → `plan` → review → `apply` → capture outputs → confirm staging reachable), and teardown/cost notes.
  - [x] Add **PV-002** to `docs/pending-verifications.md` per AC #7 (status ⏳ OPEN; gate: before QV-009/QV-084 rely on staging). **Front-loaded before implementation** (table row + Notes: deferral scope, prerequisites, ordered runbook, before-production steps).
  - [x] Run **`security-reviewer`** over the IAM/Secrets/SG/networking code; address findings (least-privilege, no `0.0.0.0/0` ingress to data stores, encryption everywhere). **No CRITICAL; core AC #5 reqs PASS.** Hardening fixes applied (see Completion Notes / Security Review).

## Dev Notes

### Scope discipline
QV-008 = **author the Terraform** for a reproducible staging stack + remote state/locking + per-env workspaces + offline validation, with the **live apply deferred** to a credentialed human (PV-002). **Not this story:** Kubernetes workload manifests/Helm charts (that's deployment — QV-084 CD), observability stack wiring (QV-009), CloudFront/WAF/production env (later), GitOps/Argo. Provision *infrastructure definitions*, not app deployments. Keep `production` out of scope but make the code workspace-ready for it.

### Why apply is not automated (environment + safety reality)
- **No AWS access here.** Like PV-001 (docker couldn't run on the macOS 12 dev box), the implementing environment has no AWS account/credentials, so `plan`/`apply` cannot run. Everything offline (`fmt`/`validate`/`tflint`) **can** and must pass.
- **Cost + irreversibility.** EKS control plane, multi-AZ RDS, ElastiCache, NAT gateways accrue hourly cost and are slow to destroy cleanly. An AI agent must **not** create them unattended. The story is "infra as reviewed code"; a human runs the rollout via the runbook. This is the D8 "no click-ops" intent — and equally "no robo-ops".

### What already exists / context to build on
- **Greenfield infra:** there is **no** `infra/` or Terraform in the repo yet (verified). This is the first IaC. Top-level dirs today: `backend/ frontend/ plans/ docs/ scripts/ _bmad/ _bmad-output/ design-artifacts/` + `docker-compose.yml`.
- **Topology to mirror** (`plans/08` §3): managed PostgreSQL (RDS/Aurora multi-AZ + read replica later), Redis (ElastiCache), object store (S3); EKS deployments `web`/`api` (HPA), `worker` (KEDA queue-depth), `beat` (singleton); ALB ingress → `api`, CloudFront → `web` (CDN/WAF later); **External Secrets Operator → Secrets Manager**; NetworkPolicies. QV-008 lays the **cloud substrate** for that (cluster + data stores + secrets + IAM), not the workloads.
- **App config contract** (`backend/src/quantvista/core/config.py`): the app reads `DATABASE_URL`, `ADMIN_DATABASE_URL`, `REDIS_URL`, `S3_*`, `JWT_SECRET` from env (`pydantic-settings`). The Terraform outputs (RDS/Redis endpoints, bucket names) and Secrets Manager entries must line up with these names so QV-084 can inject them — don't invent a different secret schema.
- **CI pattern to reuse** (`.github/workflows/ci.yml`): `detect-changes` (dorny/paths-filter) already gates `backend`/`frontend` jobs and a `CI success` aggregator (`if: always()`) is the branch-protection-required check. Add the `infra` filter+job the same way (skips are fine — that's how the frontend jobs behave on backend-only PRs).
- **PV ledger pattern** (`docs/pending-verifications.md`): PV-001 is the template for PV-002 (what/why/how/gate/status table row + notes).

### Reuse — do NOT hand-roll (research & reuse rule)
- Use the official registry modules, pinned: `terraform-aws-modules/vpc/aws`, `.../eks/aws`, `.../rds/aws`, and ElastiCache via the community module or a thin resource wrapper. Confirm **current** major versions on the Terraform Registry when implementing (e.g. vpc `~> 5.x`, eks `~> 20.x`, rds `~> 6.x` — verify, don't trust these from memory). Pin the AWS provider `~> 5.0` and commit `.terraform.lock.hcl`.
- Prefer module inputs over bespoke resources for subnets, NAT, node groups, parameter/subnet groups, SGs.

### Critical constraints (project-context + infra plan)
- **Region `ap-south-1`** (D8). **No secrets in source** — DB/Redis passwords are generated (e.g. `random_password`) and stored in Secrets Manager; never in `.tf`/`.tfvars`/state-in-git. Gitignore all state and secret tfvars; commit the provider lock file.
- **Least-privilege IAM**, encryption at rest + in transit everywhere, data stores in **private** subnets with SGs scoped to EKS nodes (no `0.0.0.0/0` to RDS/Redis).
- **Forward-only, reviewed changes** (the IaC analogue of the migrations rule): all infra change via PR; remote state + DynamoDB lock prevent concurrent/clobbering applies.
- **Portability** (D8): keep provider-specific cleverness in modules so the abstraction stays swappable.

### "Definition of Done" mapping for an infra story
The standard DoD (unit/integration coverage, migrations, OpenAPI) is mostly **N/A** here. The equivalent bar:
- **Quality gate** = `terraform fmt -check` + `validate` + `tflint` green (CI `infra` job), in place of unit tests.
- **Security** = `security-reviewer` on IAM/secrets/networking; encryption + private-subnet + least-priv verified.
- **Docs** = infra README + human runbook + PV-002 ledger entry.
- **Observability/compliance/migrations** DoD lines = N/A (note as such in completion notes). No app-surface, so no research disclaimer.

### Project Structure Notes
- **New:** `infra/terraform/{versions.tf,providers.tf,README.md,.gitignore}`, `infra/terraform/bootstrap/*`, `infra/terraform/modules/{network,eks,rds,redis,storage,secrets}/*`, `infra/terraform/envs/staging/*`.
- **Modified:** `.github/workflows/ci.yml` (detect-changes `infra` filter + `infra` job + `CI success` needs), `docs/pending-verifications.md` (PV-002), root `.gitignore` if not covered by the infra-local one.
- **Untouched:** no `backend/`, `frontend/`, or DB-migration changes — this story adds infrastructure code only.

### References
- [Source: plans/sprints/sprint-00-foundations.md#QV-008] — Terraform VPC/EKS/RDS/Redis/S3/IAM/Secrets in `ap-south-1`; remote state + locking; per-env workspace; staging reachable
- [Source: plans/08-infra-devops-observability.md#4-infrastructure-as-code] — Terraform for all cloud resources, remote state + locking, per-env workspaces, no click-ops
- [Source: plans/08-infra-devops-observability.md#3-kubernetes-production] — managed RDS/ElastiCache/S3; EKS deployments; External Secrets → Secrets Manager
- [Source: plans/08-infra-devops-observability.md#1-environments] — env matrix (local/ci/staging/production); image-based promotion
- [Source: _bmad-output/planning-artifacts/architecture.md#locked-decisions] — D8 AWS `ap-south-1` + Terraform (portable)
- [Source: plans/09-roadmap-and-delivery.md#4-definition-of-done] — DoD (mapped to infra equivalents above)
- [Source: docs/pending-verifications.md] — PV-001 pattern for the PV-002 deferral; gate names QV-008/QV-084
- [Source: backend/src/quantvista/core/config.py] — env var / secret names the Terraform outputs + Secrets Manager must match
- [Source: .github/workflows/ci.yml] — `detect-changes` paths-filter + `CI success` aggregator pattern to extend with `infra`
- [Source: _bmad-output/project-context.md] — no secrets in source; AWS Secrets Manager/SSM; `ap-south-1`; Terraform/K8s/Helm

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Code, dev-story workflow).

### Debug Log References

**Toolchain (this box has no terraform/tflint/aws — macOS 12 Monterey, Intel).** Installed
pinned binaries into the session scratchpad (no system/Homebrew changes, nothing committed):
Terraform **1.9.8** (`darwin_amd64`) + tflint **0.53.0**, both verified runnable on Monterey.
Shared `TF_PLUGIN_CACHE_DIR` so the AWS provider downloads once.

**Offline validation — all 8 configs green** (`terraform fmt -check -recursive` over the whole
tree = OK; per-config `init -backend=false` + `validate` + `tflint`):

| Config | fmt | init -backend=false | validate | tflint |
|--------|-----|---------------------|----------|--------|
| `bootstrap` | ✅ | ✅ aws v5.100.0 | ✅ Success | ✅ clean |
| `modules/network` | ✅ | ✅ vpc ~> 5.13 | ✅ Success | ✅ clean |
| `modules/eks` | ✅ | ✅ eks ~> 20.24 | ✅ Success | ✅ clean |
| `modules/rds` | ✅ | ✅ rds ~> 6.10 | ✅ Success | ✅ clean |
| `modules/redis` | ✅ | ✅ | ✅ Success | ✅ clean |
| `modules/storage` | ✅ | ✅ | ✅ Success | ✅ clean |
| `modules/secrets` | ✅ | ✅ | ✅ Success | ✅ clean |
| `envs/staging` | ✅ | ✅ aws + random ~> 3.6 | ✅ Success | ✅ clean |

`.terraform.lock.hcl` generated for the two root configs (`bootstrap`, `envs/staging`) with
multi-platform hashes (`linux_amd64`, `darwin_amd64`, `darwin_arm64`) so committed locks work
in Linux CI. `terraform plan`/`apply` deliberately **NOT** run (no AWS creds → PV-002).

### Completion Notes List

- **Scope:** authored the full staging Terraform (VPC/EKS/RDS/Redis/S3/IAM-IRSA/Secrets,
  `ap-south-1`) on pinned registry modules + remote-state bootstrap + workspace-ready env, with
  offline validation green locally and a new paths-filtered CI `infra` job. Live apply deferred to
  a human (PV-002).
- **Task 1 deviation (intentional, technically required):** `versions.tf`/`providers.tf` placed
  per **root module** (`bootstrap/`, `envs/staging/`) rather than as a top-level file. A top-level
  `provider "aws"` referencing `var.aws_region` with no resources/variables fails `terraform
  validate`; Terraform configures providers in root modules, not by directory inheritance. Reusable
  modules declare `required_providers` only. Top-level keeps `README.md` + `.gitignore`.
- **Secrets/password flow (no dependency cycle):** `random_password` (alphanumeric, to keep the
  assembled `DATABASE_URL`/`REDIS_URL` escaping-safe) generated in the **env root**, passed into
  `rds`/`redis` (master password / AUTH token) **and** `secrets` (which assembles the Secrets
  Manager entries). No module depends back on `secrets`. RDS `manage_master_user_password = false`
  so our generated password is the single source.
- **Secret schema aligns with the app:** Secrets Manager entries carry `DATABASE_URL` / `REDIS_URL`
  matching `backend/src/quantvista/core/config.py`, so QV-084 CD can inject them unchanged.
- **PV-002 front-loaded** into `docs/pending-verifications.md` before implementation (per user
  request) — row + Notes (deferral scope, prerequisites, ordered bring-up runbook, before-production
  steps, config/secret name alignment).
- **DoD mapping (infra story):** quality gate = `fmt`/`validate`/`tflint` (CI `infra` job) in place
  of unit tests ✅; security = `security-reviewer` on IAM/secrets/networking (in progress);
  docs = README + runbook + PV-002 ✅. Migrations/OpenAPI/observability DoD lines = **N/A** (no
  app surface). No research disclaimer (no product output).

### File List

**New — `infra/terraform/`:**
- `.gitignore`, `README.md`
- `bootstrap/{versions,providers,variables,main,outputs}.tf`, `bootstrap/.terraform.lock.hcl`
- `modules/network/{versions,variables,main,outputs}.tf`
- `modules/eks/{versions,variables,main,outputs}.tf`
- `modules/rds/{versions,variables,main,outputs}.tf`
- `modules/redis/{versions,variables,main,outputs}.tf`
- `modules/storage/{versions,variables,main,outputs}.tf`
- `modules/secrets/{versions,variables,main,outputs}.tf`
- `envs/staging/{versions,providers,backend,variables,main,outputs}.tf`, `envs/staging/staging.tfvars`, `envs/staging/.terraform.lock.hcl`

**Modified:**
- `.github/workflows/ci.yml` — `detect-changes` `infra` filter + output; new offline `infra` job; `infra` added to `ci-success` needs.
- `docs/pending-verifications.md` — PV-002 row + Notes.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-008 → `in-progress` (→ `review` on completion).

### Security Review (AI — security-reviewer)

Outcome: **no CRITICAL**; all core AC #5 requirements PASS (no public ingress to data stores;
RDS/Redis encrypted + private; IRSA trust + read policy least-privilege, ARN-scoped; no secrets
in source or outputs; state encrypted/versioned). Findings addressed in code:

- **H-2** EKS etcd envelope encryption — added CMK + `cluster_encryption_config` (`modules/eks`).
- **H-3** S3 plaintext access — added `aws:SecureTransport=false` deny policies (`modules/storage`, `bootstrap`).
- **H-4** Data-store SG egress — removed allow-all egress on RDS + Redis SGs.
- **M-1** Secrets CMK — dedicated KMS key + `kms:Decrypt` added to the ESO read policy (`modules/secrets`).
- **M-2** Secrets recovery window — explicit `recovery_window_in_days = 30`.
- **M-3** VPC flow logs — enabled (module-managed role + log group) (`modules/network`).
- **M-4** EKS control-plane audit logs — `cluster_enabled_log_types = [audit, api, authenticator]`.
- **M-5** RDS force TLS — `rds.force_ssl = 1` parameter group.
- **M-6** IMDSv2 — `http_tokens = required`, hop limit 1 on node group.
- **L-3** Redis AUTH rotation — `auth_token_update_strategy = "ROTATE"`.

Documented as human pre-apply / production items (README §Security review + pre-apply checklist):
**H-1** restrict EKS public endpoint CIDR (operator/CI ranges — apply is human-run); **M-7** optional
CMK for the state bucket/lock table; **L-1** alphanumeric passwords (entropy ample — informational);
**L-2** production RDS `deletion_protection`/`skip_final_snapshot`/`multi_az`.

### Change Log

- 2026-06-24 — QV-008 implemented: staging Terraform (VPC/EKS/RDS/Redis/S3/IAM-IRSA/Secrets,
  `ap-south-1`), remote-state bootstrap, workspace-ready env, offline validation green (8/8 configs),
  CI `infra` gate. PV-002 front-loaded. Live apply deferred to a human (PV-002).
- 2026-06-24 — Security-reviewer pass: hardening applied (EKS etcd CMK + audit logs + IMDSv2;
  S3 TLS-only policies; RDS force_ssl; removed data-store SG egress; Secrets CMK + 30-day recovery;
  VPC flow logs; Redis token rotation). Re-validated 8/8 configs green. H-1 + prod items documented.

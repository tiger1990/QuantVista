# QuantVista Infrastructure (Terraform) — QV-008

Reproducible AWS **staging** infrastructure as Terraform: VPC, EKS, RDS PostgreSQL,
ElastiCache Redis, S3, IAM (IRSA), and Secrets Manager in **`ap-south-1`** (locked
decision **D8**). Remote state + locking; the same code serves future environments
via Terraform **workspaces**.

> ⚠️ **Execution boundary.** This repo contains **authored + offline-validated**
> Terraform. It does **not** stand up live infrastructure. `terraform apply` (and
> anything that creates real AWS resources) is run by a **credentialed human** via
> the [runbook](#live-bring-up-runbook-human-run) below — never by CI or an agent.
> The deferral is tracked as **PV-002** in [`docs/pending-verifications.md`](../../docs/pending-verifications.md).

## Layout

```
infra/terraform/
├── bootstrap/              # ONE-TIME: S3 state bucket + DynamoDB lock (local state)
├── modules/
│   ├── network/            # wraps terraform-aws-modules/vpc/aws  (~> 5.13)
│   ├── eks/                # wraps terraform-aws-modules/eks/aws  (~> 20.24)
│   ├── rds/                # wraps terraform-aws-modules/rds/aws  (~> 6.10) + SG
│   ├── redis/              # ElastiCache replication group + SG (thin wrapper)
│   ├── storage/            # S3 buckets (app, exports) — SSE/versioning/PAB
│   └── secrets/            # Secrets Manager (DB/Redis) + External-Secrets IRSA role
└── envs/staging/           # composes the modules; s3 backend; workspace-ready
```

`versions.tf` + `providers.tf` live **per root module** (`bootstrap/`, `envs/staging/`)
because a Terraform provider must be configured in a root module, not inherited from a
parent directory. Reusable modules declare `required_providers` only.

## Architecture

- **Network** — multi-AZ VPC (3 AZs), public + private subnets, NAT gateway. Subnets
  tagged for Kubernetes ELB/subnet discovery.
- **EKS** — managed node group in **private** subnets, OIDC/IRSA enabled, private API
  endpoint always on + public endpoint CIDR-restricted, access-entry authentication.
- **RDS PostgreSQL** — private subnets, storage-encrypted, **not** publicly accessible,
  security group admits only the EKS node SG on 5432. Master password generated
  (`random_password`) → Secrets Manager.
- **ElastiCache Redis** — replication group in private subnets, encryption in transit
  (AUTH token) **and** at rest, SG admits only the EKS node SG on 6379.
- **S3** — `app` + `exports` buckets: SSE-KMS, versioning, public access blocked,
  `BucketOwnerEnforced` ownership.
- **Secrets Manager** — `quantvista/<workspace>/database` and `.../redis` hold the full
  connection material (incl. `DATABASE_URL` / `REDIS_URL` matching
  `backend/src/quantvista/core/config.py`). An **IRSA role** (ARN-scoped, least-priv) lets
  the **External Secrets Operator** read exactly those two secrets.

No secret values are committed or output — passwords are generated at apply time and
stored only in Secrets Manager (and in remote state, which is encrypted + never in git).

## Offline validation (what runs here + in CI)

No credentials needed:

```bash
cd infra/terraform
terraform fmt -check -recursive
for d in bootstrap modules/* envs/staging; do
  terraform -chdir="$d" init -backend=false
  terraform -chdir="$d" validate
  tflint --chdir="$d"
done
```

CI runs exactly this in the paths-filtered **`infra`** job (`.github/workflows/ci.yml`) —
**no** `plan`/`apply`. Pinned: Terraform **1.9.8**, tflint **0.53.0**, AWS provider
**~> 5.0** (hashes in each root `.terraform.lock.hcl`, committed).

## Security review + pre-apply checklist

`security-reviewer` ran over the IAM/Secrets/SG/networking code (QV-008): **no CRITICAL**,
core requirements PASS (no public ingress to data stores, RDS/Redis encrypted + private,
IRSA least-privilege ARN-scoped, no secrets in source/outputs). Hardening fixes baked into
the code: EKS etcd CMK encryption + audit logs + IMDSv2; S3 TLS-only bucket policies;
RDS `rds.force_ssl`; removed data-store SG egress; Secrets Manager CMK + 30-day recovery;
VPC flow logs; Redis token-rotation strategy.

**A human must confirm these before `terraform apply`:**

- [ ] **H-1** — set `cluster_endpoint_public_access_cidrs` in `staging.tfvars` to real
      operator/CI ranges (or `cluster_endpoint_public_access = false`). Default is `0.0.0.0/0`.
- [ ] **Production only** — `db_multi_az = true`, RDS `deletion_protection = true` +
      `skip_final_snapshot = false`, `single_nat_gateway = false`, restricted endpoint CIDRs.
- [ ] **M-7 (defense-in-depth)** — consider a customer-managed KMS key for the state bucket +
      DynamoDB lock table (currently AWS-managed keys; state is still encrypted).

## Live bring-up runbook (human-run)

Run on a workstation with an **AWS account**, a Terraform-capable **IAM/OIDC role**,
**Terraform ≥ 1.6**, **AWS CLI v2**, and **kubectl**. Region `ap-south-1`.

```bash
# 0. Authenticate (example: SSO)
aws sso login            # or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY

# 1. Remote-state bootstrap (ONCE per account; creates the state bucket + lock table)
cd infra/terraform/bootstrap
terraform init
terraform apply                       # review, then approve
#    -> note outputs: state_bucket_name, lock_table_name

# 2. Initialise the staging env against the S3 backend
cd ../envs/staging
terraform init                        # wires the s3 backend from bootstrap

# 3. Select the workspace (state isolated per workspace)
terraform workspace new staging       # first time
terraform workspace select staging

# 4. Plan + HUMAN REVIEW (scrutinise IAM, SGs, public access, encryption)
terraform plan -var-file=staging.tfvars

# 5. Apply (provisions VPC/EKS/RDS/Redis/S3/Secrets/IAM — slow, costs money)
terraform apply -var-file=staging.tfvars

# 6. Capture outputs (endpoints + ARNs only; no secrets)
terraform output

# 7. Confirm staging reachable
aws eks update-kubeconfig --region ap-south-1 --name quantvista-staging
kubectl get nodes
#    -> RDS/Redis are private: resolve their endpoints from in-cluster, not your laptop.
```

After a clean run, close **PV-002** in `docs/pending-verifications.md` (✅ + date/account)
and tick the QV-008 live subtask.

### Production later

`production` is intentionally out of scope but the code is workspace-ready:
`terraform workspace new production` + a `production.tfvars` (multi-AZ on, larger sizing,
`single_nat_gateway = false`, RDS `deletion_protection`/backups, restricted endpoint
CIDRs). Add CloudFront/WAF/DNS and re-run `security-reviewer` before go-live. See the
PV-002 "before production" notes in the ledger.

## Teardown / cost notes

- `terraform destroy -var-file=staging.tfvars` in `envs/staging` tears down the env.
  The **bootstrap** bucket has `prevent_destroy = true` — empty + remove it deliberately.
- Cost drivers when live: EKS control plane (hourly), NAT gateway(s), multi-AZ RDS,
  ElastiCache nodes. Staging defaults keep these minimal (single NAT, `db.t3.medium`,
  `cache.t3.micro`, no multi-AZ). **Destroy staging when idle.**

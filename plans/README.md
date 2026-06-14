# QuantVista — Plans

This directory holds **all plans and their refinements** for QuantVista, an institutional-grade
stock intelligence & portfolio analytics platform (productized as a multi-tenant SaaS).

## How to read this

Start at **`00-overview-and-decisions.md`** — it carries the executive summary, the locked
product/architecture decisions, and the map of every other document.

## Document map

| # | Document | Purpose |
|---|----------|---------|
| — | `00-overview-and-decisions.md` | Vision, locked decisions, glossary, doc index |
| 01 | `01-prd.md` | Product requirements: personas, user stories, freemium tiers, scope, success metrics |
| 02 | `02-architecture.md` | System architecture, modular-monolith→microservices strategy, multi-tenancy, tech stack |
| 03 | `03-data-architecture.md` | **Data licensing (critical)**, data model/ERD, point-in-time correctness, partitioning, caching |
| 04 | `04-api-contracts.md` | REST API design, versioning, auth, response envelope, key endpoint contracts |
| 05 | `05-domain-and-quant.md` | Domain/class design, factor & scoring engine, portfolio optimization, backtesting rigor, ML |
| 06 | `06-scheduler-and-jobs.md` | Celery/Redis orchestration, job catalog, idempotency, pipeline correctness |
| 07 | `07-security-and-compliance.md` | AuthN/Z, tenant isolation (RLS), secrets, non-advice posture, DPDP, audit logging |
| 08 | `08-infra-devops-observability.md` | Docker, Kubernetes, CI/CD, environments, IaC, monitoring, logging, SLOs |
| 09 | `09-roadmap-and-delivery.md` | Phased roadmap for a funded team, workstreams, RACI, milestones, risk register, estimates |
| — | `sprints/` | **Sprint-by-sprint, ticket-ready backlog** (QV-### tickets) expanding doc 09 — see `sprints/README.md` |
| F1 | `future-ria-compliance.md` | **Separate** plan: SEBI/SEC RIA-grade advisory (KYC, suitability, advice records) |
| F2 | `future-us-market-expansion.md` | **Separate** plan: S&P 100 / US market expansion |
| F3 | `future-scale-microservices.md` | **Separate** plan: service extraction & horizontal scale |

## Convention

- Every plan and any refinement lives in this directory.
- File names are kebab-case; numeric prefixes order the core plan, `future-` prefixes hold deferred scope.
- Refine in place (preferred). For material changes, append a dated `## Refinement — YYYY-MM-DD` section
  at the bottom of the affected document and note it in `00-overview-and-decisions.md` → Change Log.

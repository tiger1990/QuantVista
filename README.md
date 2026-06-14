# QuantVista (FinanceStockManager)

India-first equity research platform — a **modular monolith** (Python 3.13 / FastAPI) with a
Next.js / TypeScript frontend. Research signals only, **not** personalised advice.

## Repository layout

| Path | What |
|------|------|
| `backend/` | Python 3.13 backend — `quantvista` namespace package (bounded contexts), Alembic DB layer, tooling. See `backend/README.md`. |
| `frontend/` | Next.js / TypeScript / MUI app (feature folders). See `frontend/README.md`. |
| `plans/` | Design source of truth (PRD, architecture, data model, sprints). |
| `docs/` | Generated project documentation (architecture, data models, dev guide). |
| `_bmad/`, `_bmad-output/` | BMAD method config and artifacts (epics, stories, sprint status, `project-context.md`). |
| `scripts/` | Dev helper scripts. |
| `design-artifacts/` | Reserved for UX / design outputs. |

## Architecture in one paragraph

The backend is a modular monolith where each **bounded context** (`identity`, `market_data`,
`news`, `analytics`, `portfolio`, `alerts`, `core`) is a hard seam: contexts talk only through one
another's published `interfaces` (Python `Protocol`/ABC) or domain events — never another context's
internals or DB tables. `import-linter` enforces the dependency DAG in CI. One backend image runs
three roles (`api` / `worker` / `beat`) by command. Multi-tenancy is enforced by PostgreSQL
Row-Level Security; reference/market data is global (no `tenant_id`). See `plans/02-architecture.md`.

## Getting started

- Backend: `backend/README.md`
- Frontend: `frontend/README.md`
- One-command local stack (Postgres/Redis/MinIO/api/worker/beat/web) arrives in **QV-002**.

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

## Getting started — local stack (one command)

```bash
cp .env.example .env          # adjust if needed (no real secrets committed)
docker compose up --build     # builds backend+frontend images, boots the stack
```

This brings up the full environment on the `quantvista-net` network:

| Service | Image / build | Port(s) | Purpose |
|---------|---------------|---------|---------|
| `postgres` | postgres:16-alpine | 5432 | Database (creates a non-superuser `quantvista_app` role on first init) |
| `redis` | redis:7-alpine | 6379 | Cache · Celery broker/result · Streams |
| `minio` | minio/minio | 9000 / 9001 | S3-compatible object store (console on 9001) |
| `migrate` | backend image | — | One-shot: `alembic upgrade head` (admin role) |
| `seed` | postgres:16-alpine | — | One-shot: loads idempotent `seed_reference.sql` |
| `api` | backend image | 8000 | FastAPI (`uvicorn`) |
| `worker` | backend image | — | Celery worker |
| `beat` | backend image | — | Celery beat scheduler |
| `web` | frontend image | 3000 | Next.js app |

`api`/`worker`/`beat` are the **same image**, differing only by `command`. They start after
`migrate`+`seed` complete and `postgres`/`redis` are healthy.

```bash
curl http://localhost:8000/api/v1/health   # {"success":true,"data":{"status":"ok"},...}
open http://localhost:3000                  # web
open http://localhost:9001                  # MinIO console

docker compose down        # stop
docker compose down -v     # stop + wipe volumes (pg_data/redis_data/minio_data)
```

Per-stack details: `backend/README.md`, `frontend/README.md`.

> **Note:** the live stack needs a Docker engine. On macOS 13+ use Docker Desktop; on macOS 12
> (Monterey) use **Colima** (`brew install colima && colima start`) or Docker Desktop ~4.27.

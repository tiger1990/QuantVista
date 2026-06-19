# Pending Verifications (verification debt)

Living ledger of work that has been **merged on accepted risk** because some verification step
could not be completed in the implementing environment. Each item names *what* is unverified, *why*,
*how* to verify, and the **hard gate** by which it must be closed.

> Review this list at the start of every sprint and before any story listed as a blocking gate.

| ID | Item | Why deferred | How to verify | Gate (must close before) | Status |
|----|------|--------------|---------------|--------------------------|--------|
| PV-001 | **QV-002 local stack** — live `docker compose up` smoke test (AC #1–3: all services healthy, `GET /api/v1/health` → 200 envelope, web on :3000, seed loaded, worker/beat ready, images build) | Primary dev machine (macOS 12 Monterey, Intel) cannot run any Docker engine — Colima/Lima need QEMU (Homebrew won't build it on Monterey, Tier-3) and Docker Desktop is unsupported on macOS 12. Static checks all pass (`docker compose config` valid; backend + frontend gates green). | On a Docker-capable machine: `git checkout master` (QV-002 is merged), `cp .env.example .env`, `docker compose up --build`; confirm all services healthy, `curl localhost:8000/api/v1/health` → 200, `curl localhost:3000` → 200, `worker`/`beat` logs ready, spot-check a seeded reference row. | **Start of QV-004** (PostgreSQL + Alembic + RLS scaffolding — first story needing live Postgres + the `quantvista_app` role wired in QV-002) | ⏳ OPEN |

## Notes

- **PV-001:** if the live run surfaces a bug (e.g. Celery `-A` discovery, the `migrate`/`seed`
  ordering, the Next.js standalone build, or the `quantvista_app` grants), fix it as a follow-up on
  a `fix/qv-002-*` branch — do not block QV-004 planning, but it must be green before QV-004 code
  lands. Detail: `_bmad-output/implementation-artifacts/1-2-qv-002-local-dev-environment-docker-compose.md`
  and `plans/sprints/sprint-00-foundations.md` (QV-002 deferred-verification note).

## How to close an item

1. Run the verification on a capable machine.
2. If green: set Status to ✅ CLOSED (date + machine), check the corresponding story subtask, and
   remove the gate from any blocked story.
3. If red: open a `fix/*` branch, link it here, keep Status ⏳ OPEN until merged + re-verified.

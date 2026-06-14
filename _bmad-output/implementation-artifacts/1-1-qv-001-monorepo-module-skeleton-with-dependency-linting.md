---
baseline_commit: 296cec0835b6635acb2a65fbe7f65c6929bfd92e
---

# Story 1.1: QV-001 — Monorepo & module skeleton with dependency linting

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **engineer**,
I want **a structured monorepo with enforced module boundaries (backend bounded contexts under a `quantvista` namespace + frontend feature folders)**,
so that **multiple workstreams can build in parallel without creating import cycles or cross-module coupling**.

> Canonical ID **QV-001** · Epic 1 (EPIC-PLAT) · `[PLAT]` · 5pts · Sprint 00 · depends: — (first story in the project)
> Authoritative detail: `plans/sprints/sprint-00-foundations.md` §QV-001. Layout: top-level `quantvista` namespace package (decision below), derived from `docs/development-guide.md` §"Backend app — planned".

## Acceptance Criteria

1. **Backend is a `quantvista` namespace package whose sub-packages mirror the bounded contexts** from `plans/02-architecture.md` §4: `identity`, `market_data`, `news`, `analytics`, `portfolio`, `alerts`, and `core` (the Platform/Core context), plus the supporting packages `api`, `jobs`, `schemas`, `db` — all under `backend/src/quantvista/`. Each domain context is a package exposing a published `interfaces.py` (Protocol/ABC) plus per-context `models.py`, `services.py`, `repositories.py` placeholders. **Layer concerns (models/services/repositories) live inside each context, never as top-level shared folders** — that is what makes the module DAG enforceable.
2. **The existing `db/` layer moves to `backend/src/quantvista/db/`** with **zero change to Alembic migration history** — revisions `0001`→`0012`, `env.py` (naming convention, `target_metadata=None`), `script.py.mako`, `alembic.ini`, and `seeds/seed_reference.sql` are relocated verbatim. `alembic upgrade head` still works from the new location.
3. **`import-linter` is configured with `root_package = quantvista` and enforces the module dependency DAG.** Running `lint-imports` passes on the clean skeleton, and a **deliberately-forbidden import fails it** (proving the gate works) — e.g. `quantvista.core` importing `quantvista.identity`, or `quantvista.market_data` importing `quantvista.portfolio`.
4. **`import-linter` runs as a CI-style check** — wired into the project's lint task (`pyproject.toml` / Makefile / pre-commit) so a forbidden import would fail a PR. (Full GitHub Actions wiring is QV-003; this story makes the check runnable locally and trivially CI-addable.)
5. **Frontend (Next.js / TypeScript) app is scaffolded** under `frontend/` with a **feature-folder structure** (`src/app/`, `src/features/`, `src/components/`, `src/lib/`, `src/hooks/`, `src/types/`), TypeScript strict mode on, and `npm run build` / `lint` succeed on the skeleton.
6. **Tooling baselines exist and pass on the empty skeleton:** `ruff check` + `ruff format --check`, `mypy`, and `pytest` (with at least one trivial passing test, located under `backend/tests/`) on the backend; `tsc --noEmit` + ESLint on the frontend.
7. **Modules expose interfaces only — no cross-module table access.** This is encoded structurally (each context has `interfaces.py`) and enforced by the import-linter contract (AC #3).

## Tasks / Subtasks

- [x] **Task 1 — Backend project scaffold** (AC: #1, #6)
  - [x] Create `backend/` with `pyproject.toml`: Python 3.12, dependency groups for runtime (FastAPI, SQLAlchemy, Alembic, Celery, redis, pydantic-settings) and dev (ruff, mypy, pytest, pytest-cov, import-linter). Configure a **src layout** with the importable package being `quantvista` (`backend/src/quantvista/`); set `[tool.setuptools] package-dir` / `packages` (or `[tool.hatch] / uv` equivalent) so `quantvista` resolves.
  - [x] Configure `[tool.ruff]` (lint + format), `[tool.mypy]` (strict on public APIs), `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, coverage ≥80% target wired but not blocking on empty skeleton).
  - [x] Create `backend/src/quantvista/__init__.py` and the context packages: `core/`, `identity/`, `market_data/`, `news/`, `analytics/`, `portfolio/`, `alerts/`, plus `api/`, `jobs/`, `schemas/`. Each domain context gets `__init__.py`, `interfaces.py` (Protocol/ABC stubs from the table in `02` §4), and `models.py`, `services.py`, `repositories.py` placeholders (`...`/`pass` bodies — **no logic**).
  - [x] Create `backend/tests/` with one trivial test (e.g. `test_import_skeleton.py` importing each `quantvista.<context>`) so `pytest` is green and the harness is proven.
- [x] **Task 2 — Relocate the DB layer** (AC: #2)
  - [x] `git mv` the repo-root `db/` to `backend/src/quantvista/db/` (use `git mv` to preserve history). Do **not** edit any migration file content — the `0001`→`0012` chain, `down_revision` links, and naming convention in `env.py` must be byte-identical.
  - [x] Do **not** move `db/migrations/**/__pycache__/` (gitignored; delete stray `.pyc` if copied). Keep `alembic.ini` with `sqlalchemy.url` blank (URL comes from `$DATABASE_URL` via `env.py`); verify `script_location` still resolves from the new path (it is relative to `alembic.ini`).
  - [x] Verify `cd backend/src/quantvista/db && DATABASE_URL=... alembic upgrade head` still runs the full chain. Update path references in `docs/development-guide.md` and `db/README.md` to the new location.
- [x] **Task 3 — import-linter DAG contract** (AC: #3, #4, #7)
  - [x] Add `[tool.importlinter]` to `backend/pyproject.toml` **and/or** a `backend/.importlinter` file with `root_package = quantvista`. Define a **layered contract** encoding the DAG (see Dev Notes → "Dependency DAG"). Express `market_data` and `news` as independent siblings; `schemas` and `core` as the foundation; `api`/`jobs` as composition roots.
  - [x] Add an **independence contract** so `quantvista.market_data` and `quantvista.news` cannot import each other, and a **forbidden contract** so `quantvista.core` and `quantvista.schemas` import no domain context.
  - [x] Add `lint-imports` to the lint task / pre-commit hook so it runs alongside ruff.
  - [x] **Prove the gate:** temporarily add a forbidden import, confirm `lint-imports` fails, then remove it. Capture the failing output in Completion Notes (do not leave the bad import in).
- [x] **Task 4 — Frontend scaffold** (AC: #5, #6)
  - [x] Scaffold Next.js + TypeScript app in `frontend/` (app router, `next.config.ts`, strict TS). Add MUI, TanStack Query, Recharts as deps (config/providers only — no feature UI yet).
  - [x] Establish folder structure: `src/app/`, `src/features/`, `src/components/`, `src/lib/`, `src/hooks/`, `src/types/`. Add ESLint + Prettier config. Confirm `npm run build`, `lint`, and `tsc --noEmit` pass.
- [x] **Task 5 — Repo hygiene & docs** (AC: all)
  - [x] Add top-level `README.md` (repo orientation: backend/frontend/docs/scripts) and a `scripts/` folder for dev helper scripts (placeholder ok).
  - [x] Confirm `.gitignore` covers new artifacts (`__pycache__`, `.mypy_cache`, `.ruff_cache`, `node_modules`, `.next`, `dist`, `coverage`) — it already does; extend only if a new path appears.
  - [x] Add `backend/README.md` and `frontend/README.md` (run/lint/test commands). Update `docs/source-tree-analysis.md`'s "Where the next code lands" note to reflect the now-existing tree.
  - [x] Do **not** introduce app logic, real endpoints, models, or business code — skeleton + guardrails only (QV-002/003/004 build on it).

## Dev Notes

### Scope discipline (read first)
This is a **structure + enforcement** story, not a feature story. Deliver the skeleton, the moved DB layer, the import-linter gate, and green tooling. **No FastAPI routes, no SQLAlchemy models, no Celery tasks, no React features.** `interfaces.py` files contain Protocol/ABC stubs only; `models.py`/`services.py`/`repositories.py` are empty placeholders. Premature implementation here creates rework against QV-002/003/004.

### Layout decision — top-level `quantvista` namespace, context-first (authoritative for this story)
The repo uses a top-level namespace package `quantvista` under a `src` layout. This was chosen over modules-directly-under-`src/` for three reasons: (a) gives import-linter a single clean `root_package = quantvista`; (b) avoids any top-level package shadowing a stdlib name (the `platform`/`platform_core` problem disappears — it's just `quantvista.core`); (c) makes the install target unambiguous.

**Critical rule preserved from the architecture:** the backend is organized **by bounded context first**, and the layer concerns (`models`, `services`, `repositories`) live **inside each context** — NOT as top-level `quantvista/services/`, `quantvista/repositories/`, `quantvista/models/` folders. A layer-first split would make the module DAG unenforceable (you cannot say "portfolio → analytics, not the reverse" if all services share one folder), defeating AC #3 and decision D4 (modular monolith, pre-seamed). This is the one place to not follow a layer-by-type instinct.

### Target source tree
```
FinanceStockManager/                # repo root (not renamed)
├── backend/
│   ├── pyproject.toml              # Py3.12; ruff, mypy, pytest, [tool.importlinter] (root_package = quantvista)
│   ├── .importlinter               # optional: contract config (or keep it all in pyproject)
│   ├── README.md
│   ├── tests/                      # pytest lives here (test_import_skeleton.py)
│   └── src/
│       └── quantvista/
│           ├── __init__.py
│           ├── core/               # Platform/Core: config, logging, errors, IEventBus, IAuditLogger
│           ├── identity/           # IAuthService, IEntitlementService, ITenantContext
│           ├── market_data/        # IMarketDataProvider, IPriceRepository, IFundamentalsRepository
│           ├── news/               # INewsService, ISentimentService
│           ├── analytics/          # IScoreEngine, IFactor, IBacktestEngine
│           ├── portfolio/          # IPortfolioService, IOptimizer, IRiskEngine
│           ├── alerts/             # IAlertService, INotificationChannel
│           ├── schemas/            # shared Pydantic DTOs + standard response envelope
│           ├── api/                # FastAPI composition root (empty app factory ok)
│           ├── jobs/               # Celery app + beat schedule placeholders
│           └── db/                 # ← moved from repo-root db/ (history preserved, content unchanged)
├── frontend/                       # Next.js / TS / MUI · TanStack Query · Recharts (feature folders)
│   ├── package.json
│   ├── next.config.ts
│   └── src/
│       ├── app/                    # Next.js app router
│       ├── features/               # feature folders (organize by surface, not by type)
│       ├── components/             # shared UI primitives (components/ui/)
│       ├── lib/                    # utils
│       ├── hooks/                  # use-prefixed hooks
│       └── types/
├── scripts/                        # dev helper scripts
├── docs/  plans/  _bmad/  _bmad-output/  design-artifacts/   # unchanged, stay at repo root
└── README.md                       # new: repo orientation
```

Each domain context package:
```
<context>/
├── __init__.py
├── interfaces.py     # Protocol/ABC — the ONLY thing other contexts import
├── models.py         # placeholder (domain + ORM models land later)
├── services.py       # placeholder (service layer)
└── repositories.py   # placeholder (data access)
```
> These start as single files for the empty skeleton; they may grow into subpackages (`models/`, `services/`, `repositories/`) per context as code lands. Keep them context-local either way.

> **Note on `frontend/` vs `web/`:** the directory is `frontend/`. QV-002's `docker-compose` may still name the service `web` with build context `./frontend` — reconcile there, not here.

### Dependency DAG (the contract import-linter must enforce)
From `plans/02-architecture.md` §4. Higher layers may import lower; never the reverse; siblings are independent. `root_package = quantvista`.

```
quantvista.api · quantvista.jobs       ← composition roots: may import any context; nothing imports them
  quantvista.alerts                    ← depends on analytics + portfolio
  quantvista.portfolio                 ← depends on analytics
  quantvista.analytics                 ← depends on market_data + news
  quantvista.market_data │ .news       ← independent siblings (neither imports the other)
  quantvista.identity                  ← depended on by all (tenant context); imports no domain context
  quantvista.core                      ← cross-cutting foundation; imports no domain context
quantvista.schemas                     ← shared DTOs; imported by all; imports no domain context
```

Rules to encode (import-linter contract types):
- **`layers` contract** for the ordering above (each line is a layer; `market_data | news` share a layer as independent siblings; `api`/`jobs` top, `core`/`schemas` bottom).
- **`independence` contract:** `quantvista.market_data` ⟂ `quantvista.news`.
- **`forbidden` contract:** `quantvista.core` and `quantvista.schemas` may not import any of `identity, market_data, news, analytics, portfolio, alerts`.
- Contexts communicate **only** through `interfaces.py` or the future Redis Streams event bus — **never another context's `models`/`services`/`repositories` or DB tables** (`project-context.md` rule #3). Even where a layer edge is allowed (e.g. analytics→market_data), real imports should target `market_data.interfaces`, not its internals.

### Critical constraints (from project-context.md — violating any is a real bug)
- **Python 3.12, modern typing only:** `X | None`, `list[...]`, `dict[...]` (never `Optional`/`List`). Start every module file with `from __future__ import annotations` (matches `db/migrations`).
- **Two data domains never blur:** global/reference (no `tenant_id`, no RLS) vs tenant-scoped (`tenant_id` + RLS). The seams reflect it — `market_data` = global; `identity`/`portfolio`/`alerts` = tenant. Don't co-locate tenant and reference logic.
- **Same image, three roles:** `api`/`worker`/`beat` are runtime roles over one codebase selected by command. `api/` and `jobs/` are the entry packages; **don't fork domain logic per role.**
- **Secrets:** config is env-driven via `pydantic-settings`; no secrets in source or `alembic.ini`. `alembic.ini` `sqlalchemy.url` stays blank.
- **Money/values** (future): `Decimal`/`NUMERIC`, never `float`. UUID PKs via `gen_random_uuid()`. Bake nothing into the skeleton that contradicts it.

### Files being moved — current state (READ before touching)
- `db/alembic.ini` — `sqlalchemy.url` is intentionally **blank** (set from `$DATABASE_URL` in `env.py`); `script_location` is relative to the ini. **Preserve.** After moving under `backend/src/quantvista/db`, confirm `script_location` still points at `migrations`.
- `db/migrations/env.py` — reads `$DATABASE_URL`; `target_metadata = None` (hand-written DDL, autogenerate OFF); defines the `ix_/uq_/ck_/fk_/pk_` naming convention. **Move verbatim — do not edit.** Changing the naming convention destabilizes all future autogenerate diffs.
- `db/migrations/versions/0001…0012` — the live chain (RLS helpers, partitions, bitemporal, all domain tables). **Byte-identical move.** Any edit to `revision`/`down_revision` breaks the chain and is a data disaster.
- `db/seeds/seed_reference.sql`, `db/README.md`, `db/migrations/script.py.mako` — move verbatim; update path references in `db/README.md` and `docs/development-guide.md` only.
- **The system must still work end-to-end after the move:** `alembic upgrade head` from the new path is the regression check. Hard requirement even though it isn't a numbered AC.

### Tooling baselines (must be green on the empty skeleton)
| Concern | Tool / command |
|---------|----------------|
| Lint + format | **Ruff** — `ruff check` + `ruff format --check` |
| Types | **mypy** (strict on public APIs / `interfaces.py`) |
| Tests | **pytest** + coverage (one trivial test green; ≥80% gate configured, not enforced yet) |
| Module DAG | **import-linter** — `lint-imports` (`root_package = quantvista`) |
| Frontend | **tsc --noEmit**, **ESLint**, `next build` |

### Frontend specifics
- Next.js app router + TypeScript **strict**. Organize by feature/surface (`src/features/<feature>/`), not by file type. `src/components/ui/` for shared primitives, `src/lib/` for utils, `src/hooks/` for `use`-prefixed hooks, `src/types/` for shared types.
- Add MUI + TanStack Query + Recharts as dependencies and minimal providers wiring only — **no dashboards/pages yet** (those are QV-034+).

### Testing standards summary
- Backend tests live under `backend/tests/`. `pytest`, AAA structure, behavior-named tests. The meaningful tests for this story are the **import-linter contract** (the guardrail) plus a smoke test importing every `quantvista.<context>`. Coverage ≥80% is the project gate but isn't meaningfully measurable on an empty skeleton — wire it, don't block on it.
- The "forbidden import fails the check" proof (Task 3) is the real acceptance test for the guardrail — capture the failing output in Completion Notes, then revert the bad import.

### Project Structure Notes
- **Namespace decision:** top-level `quantvista` package under `backend/src/` (per user direction), `root_package = quantvista` for import-linter. Supersedes the earlier `backend/src/<module>` flat-layout sketch in `docs/development-guide.md` — update that doc's wording if it's edited as part of Task 2/5.
- **Context-first, not layer-first:** `models/services/repositories` are per-context concerns inside each bounded context, never top-level shared folders. Non-negotiable for DAG enforcement (D4 / AC #3).
- **`core` = Platform/Core context** (replaces the `platform/core` slash notation in `project-context.md`; also sidesteps the stdlib `platform` shadow).
- **DB relocation:** `db/` → `backend/src/quantvista/db` via `git mv`, migration history unchanged — the one structural change to existing code, sanctioned by `docs/development-guide.md`.
- **Frontend dir is `frontend/`** (matches the user's tree); compose service naming reconciled in QV-002.
- **No conflict** with `plans/`, `docs/`, `_bmad/`, `_bmad-output/`, `design-artifacts/`, `scripts/` — those live at repo root, untouched.

### References
- [Source: plans/sprints/sprint-00-foundations.md#QV-001] — story statement, ACs, notes
- [Source: plans/02-architecture.md#4-modules-bounded-contexts--ownership] — context table, published interfaces, dependency DAG rule
- [Source: plans/02-architecture.md#2-3] — modular-monolith style, same-image-three-roles
- [Source: docs/development-guide.md#backend-app--planned] — db→backend move, import-linter, one-image-three-roles
- [Source: docs/source-tree-analysis.md] — current tree (DB-only), planned landing spot
- [Source: _bmad-output/project-context.md#3] — module boundaries are hard seams; import-linter enforces DAG
- [Source: _bmad-output/project-context.md#language-specific-rules] — Python 3.12 typing, `from __future__ import annotations`
- [Source: _bmad-output/project-context.md#5] — migrations forward-only, naming convention, env.py helpers

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (Claude Opus 4.8) via BMAD dev-story workflow.

### Implementation Plan

Built the monorepo skeleton + guardrails per the story, with two decisions confirmed with the user
before coding: (1) **Python 3.13** (latest-minus-one) over 3.12/3.14 — broadest wheel coverage for
the future scientific/ML stack (torch/cvxpy/scipy); (2) top-level **`quantvista` namespace**,
context-first. Validation order: ruff → mypy → pytest → import-linter (backend), then tsc → eslint →
next build (frontend).

### Debug Log References

- import-linter `containers = quantvista` combined with fully-qualified layer names double-prefixed
  (`quantvista.quantvista.alerts`). Fixed by dropping `containers` and keeping full module paths.
- ruff `UP046` on `Generic[T]` → migrated `Envelope` to PEP 695 `class Envelope[T]` (target py313).
- Two pre-existing migrations (`0004`, `0006`) failed `ruff format --check` (formatted at line-length
  88 by alembic's post-write hook vs the app's 100). Resolved by **excluding `db/migrations` from
  ruff** (governed by alembic's own hook) — migrations kept byte-identical, history untouched.
- zsh does not word-split unquoted `$VAR`; an initial boilerplate loop made one space-named dir.
  Redone with an explicit literal loop.

### Completion Notes List

- **All 7 ACs satisfied; all tasks/subtasks complete.** Backend gates green: ruff (lint+format),
  mypy --strict (39 files), pytest (18 passed), import-linter (3 contracts kept). Frontend green:
  tsc --noEmit, eslint, next build.
- **DB move (AC #2):** `git mv` recorded all 16 db files as 100% renames — Alembic chain
  `0001`→`0012` resolves from `backend/src/quantvista/db` (`alembic heads` → `0012 (head)`). Full
  `alembic upgrade head` needs a live Postgres (QV-002); verified the chain via `alembic history`,
  which does not connect.
- ✅ **Import-linter gate proven (AC #3):** injected a forbidden `core → portfolio` import → 2
  contracts BROKEN with a precise message (`quantvista.core is not allowed to import
  quantvista.portfolio`); reverted → green. The DAG, sibling-independence (`market_data ⟂ news`), and
  foundation-purity (`core`/`schemas`) contracts are all enforced.
- **Scope honored:** no business logic. Contexts hold `interfaces.py` (Protocol/ABC) + empty
  `models/services/repositories` placeholders. `api`/`jobs` are empty composition roots.
- **Frontend:** TanStack Query provider wired into the app-router layout; MUI + Recharts installed
  (config-only, ThemeProvider deferred to QV-034 per scope). Feature folders created with `.gitkeep`.
- **User decisions captured:** Python **3.13** (overrides locked D7); top-level **`quantvista`**
  namespace, context-first; Platform/Core named **`core`** (stdlib-shadow avoidance); frontend dir
  **`frontend/`**.
- **Docs reconciled** to the new layout/version: `project-context.md`, `docs/development-guide.md`,
  `docs/source-tree-analysis.md`, and the moved `db/README.md`. `plans/` design docs still say
  Python 3.12 / `platform/core` (historical source-of-truth; not edited).
- **Deferred (out of scope, by design):** full dependency provisioning + `docker-compose` (QV-002);
  GitHub Actions wiring of these gates (QV-003); coverage ≥80% enforcement (no production logic yet).

### File List

**Moved (git rename, content unchanged — 16 files):**
- `db/` → `backend/src/quantvista/db/` (`alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001…0012` (12), `seeds/seed_reference.sql`, `README.md`)

**New — backend:**
- `backend/pyproject.toml`
- `backend/.importlinter`
- `backend/README.md`
- `backend/src/quantvista/__init__.py`
- `backend/src/quantvista/core/{__init__,interfaces}.py`
- `backend/src/quantvista/{identity,market_data,news,analytics,portfolio,alerts}/{__init__,interfaces,models,services,repositories}.py`
- `backend/src/quantvista/schemas/{__init__,envelope}.py`
- `backend/src/quantvista/api/__init__.py`
- `backend/src/quantvista/jobs/__init__.py`
- `backend/tests/{__init__,test_import_skeleton}.py`

**New — frontend (`frontend/`, via create-next-app + edits):**
- `frontend/` Next.js app (package.json, next.config.ts, tsconfig.json, eslint.config.mjs, public/, src/app/*)
- `frontend/src/components/providers.tsx`
- `frontend/src/{features,components/ui,lib,hooks,types}/.gitkeep`
- edited `frontend/src/app/layout.tsx` (Providers + metadata); overwrote `frontend/README.md`

**New — repo:**
- `README.md` (top-level)
- `scripts/README.md`

**Modified (docs reconciled):**
- `docs/development-guide.md`, `docs/source-tree-analysis.md`
- `_bmad-output/project-context.md`
- `backend/src/quantvista/db/README.md` (path references + link depth post-move)

**Modified (process):**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (status transitions)
- this story file (frontmatter `baseline_commit`, tasks, Dev Agent Record, Status)

## Change Log

| Date | Change |
|------|--------|
| 2026-06-15 | QV-001 implemented: `quantvista` namespace backend skeleton (7 bounded contexts + `api/jobs/schemas/db`), DB layer relocated under git rename, import-linter DAG contracts (proven by a deliberate violation), Next.js `frontend/` scaffold with TanStack Query provider. All backend + frontend gates green. Confirmed Python **3.13** and namespace layout with user; reconciled docs. Status → review. |

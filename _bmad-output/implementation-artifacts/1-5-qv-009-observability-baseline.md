---
baseline_commit: fcaa2a84d278464c12f555b15eea25f33ba0b918
---

# Story 1.5: QV-009 — Observability baseline

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **an operator**,
I want **metrics, logs, and traces emitted from the `api` and `worker` roles from day one — structured JSON logs correlated by request/trace ID, OpenTelemetry tracing, a Prometheus `/metrics` endpoint, and Sentry error capture — all env-driven so they no-op safely where no backend is wired**,
so that **we never fly blind: every request and job is traceable, measurable, and its failures are captured**.

> Canonical ID **QV-009** · Epic 1 (EPIC-PLAT) · `[PLAT]` · 5pts · Sprint 00 · depends: **QV-008** (done, merged #11)
> Authoritative detail: `plans/sprints/sprint-00-foundations.md` §QV-009. Observability spec: `plans/08-infra-devops-observability.md` §6. Envelope + error codes: `plans/04-api-contracts.md`; `_bmad-output/project-context.md` §Framework-Specific Rules. Security/PII: `plans/07-security-and-compliance.md`.

## ⚠️ Read this first — execution boundary (partial deferral)

This story delivers **all in-application instrumentation code**, fully unit/integration-tested **offline**. It does **not** stand up live observability backends.

- **Buildable + tested now (the whole of this story's code):** structlog JSON logging + PII redaction, OpenTelemetry tracing wiring for api/worker, request-ID correlation into logs and the response envelope `meta.request_id`, the Prometheus `/metrics` endpoint + RED/worker metrics, and env-driven Sentry init. Every integration **no-ops safely when its backend env var is unset** (no OTLP endpoint → no exporter; no Sentry DSN → no init; `metrics_enabled=false` → no `/metrics`). This is a hard requirement, not a convenience: local, CI, and the no-creds dev box must all run green.
- **Deferred to a live staging env (PV-003):** the `plans/08 §6` clause **"Grafana + Sentry wired in staging"** — a reachable OTLP collector (Tempo/Jaeger), a Grafana instance with operator dashboards, a real Sentry project + DSN, and the end-to-end confirmation that traces/metrics/logs/errors actually land. **Staging does not exist yet** (`PV-002` is OPEN — no AWS account/credentials here), so this is recorded as **PV-003** (blocked on PV-002) and completed by a credentialed human. See AC #9 + Task 9.
- **Not this story at all:** SLOs, alerting rules, on-call routing, synthetic checks (→ **QV-082**); the job-observability dashboard (→ **QV-020**); frontend Sentry (→ frontend billing/UX stories); log-shipping infra (Loki/OpenSearch) and the tracing backend themselves (staging infra, PV-003). Ship the *instrumentation*, not the *backends*.

## Acceptance Criteria

1. **Single-sourced foundation observability module.** A new `quantvista/core/observability/` package holds the primitives (logging, tracing, metrics, sentry, and a correlation-context helper). It imports **no domain context** so `import-linter`'s `foundation-purity` contract stays green (`core` may not import `identity`/`market_data`/`news`/`analytics`/`portfolio`/`alerts`). The same functions serve **both** the `api` and `worker` roles — logic is single-sourced, never forked per role (project-context rule #6, "same image, three roles").

2. **Structured JSON logging (structlog).** `configure_logging(role)` configures structlog: **JSON** output when `log_json=true` (cloud), human-readable console when `false` (local default). Every record carries `timestamp` (ISO-8601 **UTC**), `level`, `logger`, `event`, `role`, and — when present — the correlation fields `request_id`, `trace_id`, `span_id` (pulled from the correlation contextvar / active OTel span). **PII-aware redaction** processor masks/drops sensitive keys case-insensitively (`password`, `token`, `authorization`, `cookie`, `set-cookie`, `secret`, `refresh`, `jwt`, `api_key`; email values masked to `a***@domain`). No secret or PII value ever reaches a log line.

3. **OpenTelemetry tracing across `api` and `worker`.** `configure_tracing(role)` builds a `TracerProvider` with a resource carrying `service.name` (`quantvista-api` / `quantvista-worker`, overridable via `otel_service_name`) and `deployment.environment = app_env`. Spans export via **OTLP** (`opentelemetry-exporter-otlp`) **only when `otel_exporter_otlp_endpoint` is set**; unset → provider installed with no exporter (traces are created but not shipped — never crash, never block on a missing collector). API is instrumented with `FastAPIInstrumentor.instrument_app(app)`; the worker with `CeleryInstrumentor().instrument()`. Active trace/span IDs flow into logs (AC #2) and the envelope (AC #4).

4. **Request-ID correlation + envelope `meta.request_id`.** An API middleware: reads inbound `X-Request-ID` or generates a UUIDv4; binds it (plus the active `trace_id`) into the correlation contextvar consumed by structlog; echoes `X-Request-ID` on the response; and ensures **success** envelopes carry `meta.request_id` (per `plans/08 §6`: "trace IDs in logs & responses (`meta.request_id`)"). It must **merge, not clobber**, existing `meta` (e.g. `next_cursor`). Error envelopes keep their canonical `{success:false,data:null,error:{code,message}}` shape; surfacing `request_id` on error responses (header + optional meta) is acceptable but must not alter `error`.

5. **Prometheus `/metrics` endpoint + RED / worker metrics.** With `metrics_enabled=true` (default on), the API exposes `GET /metrics` in Prometheus text format. **API RED:** request **count**, **error** count, and **latency** histogram, labelled by `method`, **route template** (e.g. `/api/v1/auth/login`, *not* the raw path — bounded cardinality), and `status`; plus a **per-tenant request-volume** counter (label = tenant id from request state, bounded — counters only, never a histogram label). **Worker:** task count, task-latency histogram, and failure count via Celery signals. Queue-depth / DLQ-size metrics are noted as a follow-up (need broker introspection — out of baseline scope; leave a `# TODO(QV-020)` marker). The worker (no HTTP server) exposes its registry via an **env-gated `prometheus_client` HTTP server** on `worker_metrics_port` when metrics are enabled.

6. **Sentry error tracking (backend, both roles).** `configure_sentry(role)` calls `sentry_sdk.init(dsn=settings.sentry_dsn, environment=app_env, traces_sample_rate=settings.sentry_traces_sample_rate, send_default_pii=False, integrations=[...])` with the Starlette/FastAPI and Celery integrations. **DSN unset → `init` is skipped entirely** (safe in local/CI/no-creds). Unhandled exceptions in api/worker are captured; the API's existing `internal_error` envelope path is unchanged.

7. **Config, dependencies, wiring — no secrets in source.** New env-driven `pydantic-settings` fields on `Settings` (safe local defaults, **no secret literals**): `log_level` (`"INFO"`), `log_json` (`False` local), `otel_exporter_otlp_endpoint` (`None`), `otel_service_name` (`None`), `sentry_dsn` (`None`), `sentry_traces_sample_rate` (`0.0`), `metrics_enabled` (`True`), `worker_metrics_port` (`9100`). New runtime deps added to `backend/pyproject.toml` with version floors (see Latest Tech). `create_app()` wires logging+tracing+sentry+request-ID middleware+`/metrics` for the api role; `create_celery()` (or a Celery `worker_process_init`/signals bootstrap) wires logging+tracing+sentry+worker-metrics for the worker role — both drawing from the single-sourced module (AC #1).

8. **Tests ≥ 80 % + all gates green.** Unit + integration coverage for: redaction masks each sensitive key; log records include correlation fields when the contextvar is set; the request-ID middleware generates+propagates the ID, sets the response header, and populates `meta.request_id` without dropping existing meta; `/metrics` returns `200 text/plain; version=0.0.4` containing the expected metric names; RED counters/histogram increment on a request; tracing installs a provider and **no-ops without an endpoint**; sentry **no-ops without a DSN**; worker task metrics record via the Celery signal path. `ruff check`, `ruff format --check`, `mypy --strict`, `lint-imports`, and `pytest` (coverage ≥ 80 %) all pass locally and in CI. Add `[[tool.mypy.overrides]]` `ignore_missing_imports`/`disallow_untyped_decorators` entries for any untyped OTel/prometheus/sentry modules — mirror the existing `celery` override block; do **not** weaken global strictness.

9. **Live staging wiring deferred (PV-003).** Add a `PV-003` row to `docs/pending-verifications.md` capturing: **what** is unverified (point the instrumentation at real staging backends — OTLP collector/Tempo, Grafana + operator dashboards, Sentry project/DSN — and confirm traces, metrics, logs, and errors land end-to-end), **why** (no live staging or credentials in the implementing environment; `plans/08 §6` "wired in staging"), **how** (a runbook: set `OTEL_EXPORTER_OTLP_ENDPOINT`/`SENTRY_DSN` via Secrets Manager, deploy, generate traffic, verify in Grafana/Sentry, build the operator dashboards from `plans/08 §6`), and the **gate** (must close before **QV-020** job dashboard and **QV-082** SLOs/alerting depend on live telemetry; itself **blocked on PV-002** — staging must exist first). All in-app instrumentation ships and is offline-tested in this story regardless of PV-003.

## Tasks / Subtasks

- [x] **Task 1 — Foundation module skeleton + deps + config** (AC: #1, #7)
  - [x] Create `quantvista/core/observability/` package: `__init__.py` (public `configure_observability(role)` facade + re-exports), `context.py` (correlation contextvars: `request_id`, `trace_id`, `span_id` + get/bind/clear helpers), and empty `logging.py`, `tracing.py`, `metrics.py`, `sentry.py` to be filled by later tasks. Confirm `import-linter` still green (no domain imports).
  - [x] Add runtime deps to `backend/pyproject.toml` (`structlog`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-celery`, `prometheus-client`, `sentry-sdk`) with version floors (see Latest Tech). Add `[[tool.mypy.overrides]]` for untyped modules as needed.
  - [x] Extend `core/config.py` `Settings` with the AC #7 fields (env-driven, safe defaults, no secrets). Update `tests/test_config.py` expectations.
- [x] **Task 2 — Structured JSON logging + PII redaction** (AC: #2)
  - [x] Implement `configure_logging(role)` in `observability/logging.py`: structlog processor chain (merge correlation contextvars → add level/logger/ISO-UTC timestamp → **PII redaction** → JSON renderer when `log_json` else console). `role` bound on every record.
  - [x] Redaction processor: case-insensitive key match against the AC #2 denylist; mask emails. Unit-test each key + email masking.
- [x] **Task 3 — OpenTelemetry tracing (api + worker)** (AC: #3)
  - [x] Implement `configure_tracing(role)` in `observability/tracing.py`: `Resource` (`service.name`, `deployment.environment`), `TracerProvider`, OTLP `BatchSpanProcessor` **only if** `otel_exporter_otlp_endpoint` set. Return/install idempotently (guard double-init in tests).
  - [x] Expose helpers to instrument FastAPI (`FastAPIInstrumentor.instrument_app`) and Celery (`CeleryInstrumentor().instrument()`); pull `trace_id`/`span_id` from the active span into the correlation context.
- [x] **Task 4 — Request-ID middleware + envelope meta** (AC: #4)
  - [x] Add an API middleware (Starlette `BaseHTTPMiddleware` or pure ASGI) in `api/` (composition root, may import core): bind request_id + trace_id to context, set `X-Request-ID` response header.
  - [x] Ensure success envelopes carry `meta.request_id` **merging** existing meta. Decide the cleanest hook (envelope helper vs. response post-processing) and document it. Add `request_id` to `Envelope.ok` meta path without breaking `next_cursor`/existing callers.
- [x] **Task 5 — Prometheus metrics** (AC: #5)
  - [x] API: `/metrics` endpoint + RED middleware (count/errors/latency by method/route-template/status; per-tenant volume counter). Prefer a battle-tested lib (`prometheus-fastapi-instrumentator`) or hand-roll with official `prometheus-client` if route-template labelling needs control — justify the choice in Completion Notes.
  - [x] Worker: Celery signals (`task_prerun`/`task_postrun`/`task_failure`) → task count/latency/failure metrics; env-gated `prometheus_client.start_http_server(worker_metrics_port)` in worker bootstrap. `# TODO(QV-020)` for queue-depth/DLQ.
- [x] **Task 6 — Sentry (both roles)** (AC: #6)
  - [x] Implement `configure_sentry(role)` in `observability/sentry.py`: env-gated `sentry_sdk.init` with FastAPI/Starlette + Celery integrations, `send_default_pii=False`. No-op without DSN. Unit-test the no-op path (patch `sentry_sdk.init`).
- [x] **Task 7 — Wire both roles** (AC: #1, #7)
  - [x] `api/app.py::create_app()` → `configure_observability("api")`: logging + tracing + sentry + request-ID middleware + mount `/metrics`. Keep the dependency-free `/health` behavior intact.
  - [x] `jobs/celery_app.py::create_celery()` (+ signals) → `configure_observability("worker")`: logging + tracing + sentry + worker metrics server. Don't break the existing `ping` task or `-A quantvista.jobs.celery_app` discovery.
- [x] **Task 8 — Tests + gates green** (AC: #8)
  - [x] Add `tests/test_observability_*.py` (unit) + extend an integration test asserting `meta.request_id` + `X-Request-ID` header + a recorded metric on a real request through the app. AAA structure; behavior-named.
  - [x] Run `ruff check`, `ruff format --check`, `mypy --strict`, `lint-imports`, `pytest --cov=src --cov-report=term-missing`. Fix all findings. Record exact commands + output in the Dev Agent Record.
- [x] **Task 9 — PV-003, docs, security review** (AC: #9)
  - [x] Add **PV-003** to `docs/pending-verifications.md` per AC #9 (status ⏳ OPEN; blocked on PV-002; gate before QV-020/QV-082).
  - [x] Note env vars in `.env.example` (and `docker-compose` env passthrough if applicable) — names only, **no values**.
  - [x] Run **`security-reviewer`** over the logging/redaction + Sentry (PII) + config paths; confirm no secret/PII leakage in logs or error capture. Address findings. (See **Security Review** below — 1 CRITICAL + 4 HIGH fixed in code; 3 lower deferred/documented.)

## Dev Notes

### Scope discipline
QV-009 = **emit** metrics/logs/traces from `api`+`worker` with env-driven, no-op-safe instrumentation, fully tested offline; **defer** the live staging backends (Grafana/Sentry/OTLP collector) to PV-003. **Not this story:** SLOs/alerting/on-call/synthetics (**QV-082**), job-observability dashboard (**QV-020**), frontend Sentry (frontend stories), log-shipping/tracing-backend infra (staging). Deliver instrumentation, not backends.

### Why staging wiring is deferred (environment reality)
- **No live staging, no creds.** `PV-002` (QV-008 rollout) is still OPEN — there is no reachable OTLP collector, Grafana, or Sentry project to point at, and no AWS credentials here. Everything that runs **in-process** (structlog, OTel provider, `/metrics`, Sentry `init` guard) is built and tested now; the "confirm data lands in Grafana/Sentry" step is PV-003, gated behind PV-002. Same author-now / verify-live-later split QV-008 used.

### What already exists / context to build on
- **`api/app.py`** — `create_app()` factory: `/api/v1/health` (dependency-free liveness — keep it that way), auth router, and envelope-based exception handlers (`EmailAlreadyExists`→conflict, `InvalidCredentials`/`InvalidRefreshToken`→unauthenticated, `EntitlementExceeded`→entitlement_exceeded, `RequestValidationError`→validation_error). This is the API composition root — wire observability here.
- **`jobs/celery_app.py`** — `create_celery()` factory + `ping` task; discovered via `-A quantvista.jobs.celery_app`. Worker composition root — wire worker observability here / via Celery signals. **Do not fork domain logic per role** (rule #6).
- **`schemas/envelope.py`** — `Envelope[T]` dataclass with `Envelope.ok(data, *, meta=...)` and `Envelope.fail(code,message)`; `ERROR_STATUS` code→HTTP map. `schemas` is a **zero-dependency stdlib-only leaf** — do NOT add structlog/otel imports there. `meta.request_id` injection happens at the api layer, not in `schemas`.
- **`core/config.py`** — `Settings(BaseSettings)` + `@lru_cache get_settings()`; tests call `get_settings.cache_clear()`. One Settings object backs all three roles. Extend it here.
- **`core/`** is the **foundation** layer (imported by all, imports no domain) — the correct home for observability primitives per the DAG.
- **Tenant id** for per-tenant metrics: set on request state by the QV-007 tenant-context dependency (`app.tenant_id`). Read it in the metrics middleware defensively (may be absent on unauthenticated routes like `/health`, `/metrics`).
- **PV ledger** (`docs/pending-verifications.md`): PV-001/PV-002 are the template for PV-003 (what/why/how/gate/status row + Notes).

### Reuse — do NOT hand-roll (research & reuse rule)
- Logging: **structlog** (project-context §Logging names it explicitly). Tracing: **opentelemetry-sdk** + **opentelemetry-instrumentation-fastapi** + **opentelemetry-instrumentation-celery** + **opentelemetry-exporter-otlp** — never hand-roll span propagation. Metrics: official **prometheus-client**; **prometheus-fastapi-instrumentator** is an acceptable, popular convenience for the API RED + `/metrics` (justify if used). Errors: **sentry-sdk** with its FastAPI/Starlette + Celery integrations.

### Critical constraints (project-context + plans)
- **Envelope is law:** every `/api/v1` endpoint returns `{success,data,error,meta}`; `meta.request_id` is an *addition*, never a reshaping. `/metrics` is an ops endpoint outside `/api/v1` and is exempt from the envelope (Prometheus text format).
- **No secrets in source** — DSN/OTLP endpoint come from env / Secrets Manager. **PII redaction is a compliance requirement** (`plans/07`), not a nicety: passwords, tokens, cookies, JWTs, refresh tokens must never be logged; `send_default_pii=False` in Sentry.
- **Foundation-purity import rule** — `core.observability` must not import any bounded context. If a helper needs domain data (e.g. tenant id), pass it in from the api layer; don't import upward.
- **Same image, three roles** — single-source `configure_observability(role)`; `role` ∈ {`api`,`worker`,`beat`} selects wiring, not duplicated logic.
- **No-op safety** — missing OTLP endpoint / Sentry DSN / `metrics_enabled=false` must degrade gracefully (no exceptions, no import-time network). CI and the no-creds dev box run all of this.
- **mypy strict stays strict** — add per-module `ignore_missing_imports` overrides for untyped third-party (mirror the `celery` block); never relax global config.

### "Definition of Done" mapping (`plans/09`)
- **Code + tests** = the instrumentation modules + unit/integration tests ≥80 %. **Observability** DoD line = *this story is that line* for the app surface. **Docs** = `.env.example` var names + PV-003 ledger entry + Completion Notes. **Migrations/OpenAPI** = N/A (no schema/contract change; `/metrics` is ops-only). **Compliance** = PII redaction + `send_default_pii=False` (note explicitly). No new user-facing research output → no disclaimer surface.

### Project Structure Notes
- **New:** `backend/src/quantvista/core/observability/{__init__,context,logging,tracing,metrics,sentry}.py`; `backend/tests/test_observability_*.py`.
- **Modified:** `core/config.py` (+ fields), `api/app.py` (wire + middleware + `/metrics`), `jobs/celery_app.py` (wire + signals + metrics server), `pyproject.toml` (deps + mypy overrides), `tests/test_config.py`, `.env.example`, `docs/pending-verifications.md` (PV-003). Possibly `.github/workflows/ci.yml` only if new deps need it (they install via `pip install -e .[dev]` already — verify no extra step needed).
- Keep files 200–400 lines (800 max); one concern per module.

### References
- [Source: plans/sprints/sprint-00-foundations.md#QV-009] — story + AC (OTel api/worker; structured JSON logs w/ request/trace IDs; Prometheus endpoint; Grafana + Sentry in staging).
- [Source: plans/08-infra-devops-observability.md#6-observability] — tracing w/ `meta.request_id`; RED + per-tenant volume; worker queue/latency/DLQ; data-freshness SLO; structured JSON (structlog) + PII redaction; Sentry; dashboards answer operator questions.
- [Source: plans/08-infra-devops-observability.md#7-slos--alerting] — SLO targets (context only; **alerting is QV-082**, not this story).
- [Source: _bmad-output/project-context.md] — envelope + error codes; rule #6 same-image-three-roles; §Secrets; §Testing (≥80 %, AAA); §Anti-patterns (don't bypass envelope).
- [Source: plans/07-security-and-compliance.md] — PII-aware redaction / no-PII-in-logs basis.
- [Source: docs/pending-verifications.md] — PV-001/PV-002 pattern for PV-003; PV-002 already names QV-009 as a gate (staging must exist first).
- [Source: backend/.importlinter] — `foundation-purity` (core imports no domain); layered DAG (`api`/`jobs` are composition roots).
- [Source: _bmad-output/implementation-artifacts/1-4-qv-008-iac-bootstrap-aws-staging.md] — author-now / verify-live-later deferral pattern; PV row conventions.

### Latest Tech (verified via Context7 — OpenTelemetry Python Contrib)
- **FastAPI:** `pip install opentelemetry-instrumentation-fastapi`; `FastAPIInstrumentor.instrument_app(app)`.
- **Celery:** `CeleryInstrumentor().instrument()` (call in the worker process; pairs with `opentelemetry-instrumentation-celery`).
- **OTLP export:** `pip install "opentelemetry-exporter-otlp"`; exporter reads `OTEL_EXPORTER_OTLP_ENDPOINT` (our `otel_exporter_otlp_endpoint` maps to it). Install exporter **only** wire it when endpoint present.
- **Log↔trace correlation:** the OTel logging instrumentation exposes `otelTraceID`/`otelSpanID`; we replicate this in structlog by reading the active span (`opentelemetry.trace.get_current_span().get_span_context()`) in a processor — keeps our JSON renderer authoritative rather than stdlib logging format strings.
- **Version floors (confirm current stable at implementation):** `structlog>=24.1`, `opentelemetry-sdk>=1.27`, `opentelemetry-exporter-otlp>=1.27`, `opentelemetry-instrumentation-fastapi>=0.48b0`, `opentelemetry-instrumentation-celery>=0.48b0`, `prometheus-client>=0.20`, `sentry-sdk>=2.13`. (OTel `instrumentation-*` use the `0.NNbM` line that tracks the `1.NN` core — keep the pair consistent.)

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow)

### Debug Log References

Resolved dependency versions (installed into `backend/.venv`, Python 3.13.13):
`structlog 26.1.0`, `opentelemetry-sdk/api/exporter-otlp 1.43.0`, `opentelemetry-instrumentation-* 0.64b0`,
`prometheus-client 0.25.0`, `sentry-sdk 2.64.0`.

Final gate run (all green, post security-fix):
- `ruff check .` → All checks passed! · `ruff format --check .` → all formatted
- `mypy` (strict) → Success: no issues found in 74 source files
- `lint-imports` → Contracts: 3 kept, 0 broken (foundation-purity KEPT — `core.observability` imports no domain)
- `pytest --cov=src` → **91 passed**; **TOTAL coverage 93 %** (observability modules 93–100 %)

### Completion Notes List

- **Module layout:** observability primitives live in `core/observability/` (`context`, `logging`,
  `tracing`, `metrics`, `sentry`) with a `configure_observability(role, app=...)` facade in
  `__init__`. `core` foundation-purity is preserved (import-linter green) — the per-tenant metric
  reads tenant id passed up from the api layer via `request.state`, never by importing a context.
- **No-op safety (verified by tests):** no OTLP endpoint → no exporter built; no Sentry DSN →
  `init` skipped; `metrics_enabled=false` → `/metrics` + RED middleware not mounted. Local/CI/no-creds
  all run green.
- **Metrics — hand-rolled on official `prometheus-client`** (not `prometheus-fastapi-instrumentator`)
  to control the route-**template** label (`request.scope["route"].path`) and keep cardinality bounded;
  gives typed code under mypy strict. RED = `http_requests_total` / `http_request_errors_total` (5xx +
  unhandled) / `http_request_duration_seconds`; per-tenant = `http_requests_by_tenant_total`. Worker =
  `celery_tasks_total` / `_duration_seconds` / `_failures_total` via `task_prerun/postrun/failure`
  signals; `# TODO(QV-020)` left for queue-depth/DLQ (needs broker introspection).
- **Worker wiring:** task-metric signals connect in `create_celery()` (lightweight, no ports); the
  heavier per-process config + `start_http_server(worker_metrics_port)` run in `worker_process_init`
  so importing `celery_app` never binds a port or reconfigures global logging (keeps QV-002 tests green).
- **request_id in the envelope:** `RequestContextMiddleware` rewrites only success JSON envelopes to add
  `meta.request_id` (merging existing meta like `next_cursor`); error envelopes keep their canonical
  shape, only the `X-Request-ID` header is added. `schemas.envelope` stays a zero-dependency leaf.
- **Version drift note:** `prometheus-client 0.25` emits `Content-Type: text/plain; version=1.0.0`
  (the story cited the older `0.0.4`); the endpoint is still valid Prometheus exposition — the test
  asserts against the library's `CONTENT_TYPE_LATEST` rather than a hard-coded version.
- **mypy:** added no new global relaxations; one targeted `# type: ignore[no-untyped-call]` on
  `CeleryInstrumentor()` (OTel contrib ships no `py.typed`). Processors typed via `structlog.typing`.
- **PII/compliance:** `redact_pii` masks the `SENSITIVE_KEYS` denylist (case-insensitive) + emails;
  Sentry `send_default_pii=False`. Security review (security-reviewer agent) run over
  logging/redaction/sentry/config — see Change Log / Security Review.
- **Deferred (PV-003):** live "Grafana + Sentry wired in staging" — blocked on PV-002 (no staging/creds).

### File List

**New**
- `backend/src/quantvista/core/observability/__init__.py` — `configure_observability` facade + re-exports.
- `backend/src/quantvista/core/observability/context.py` — correlation contextvars (request/trace/span id).
- `backend/src/quantvista/core/observability/logging.py` — structlog config + `redact_pii` (PII masking).
- `backend/src/quantvista/core/observability/tracing.py` — OTel provider/OTLP + FastAPI/Celery instrument helpers.
- `backend/src/quantvista/core/observability/metrics.py` — Prometheus RED + per-tenant + worker task metrics.
- `backend/src/quantvista/core/observability/sentry.py` — env-gated Sentry init (both roles).
- `backend/src/quantvista/api/middleware.py` — `RequestContextMiddleware` (correlation + `meta.request_id`).
- `backend/tests/test_observability_context.py`
- `backend/tests/test_observability_logging.py`
- `backend/tests/test_observability_tracing.py`
- `backend/tests/test_observability_metrics.py`
- `backend/tests/test_observability_sentry.py`
- `backend/tests/test_observability_app.py`
- `backend/tests/test_request_context_middleware.py`

**Modified**
- `backend/pyproject.toml` — 7 observability runtime deps.
- `backend/src/quantvista/core/config.py` — 8 env-driven observability settings.
- `backend/src/quantvista/api/app.py` — wire observability + metrics endpoint/middleware + request-context middleware.
- `backend/src/quantvista/api/deps.py` — surface `request.state.tenant_id` for the per-tenant metric.
- `backend/src/quantvista/jobs/celery_app.py` — worker observability wiring (signals + `worker_process_init`).
- `backend/tests/test_config.py` — assertions for the new settings.
- `.env.example` — observability env var docs (names only, no secrets).
- `docs/pending-verifications.md` — **PV-003** (live staging observability, blocked on PV-002).
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-009 status.

### Change Log

- **2026-07-02 — QV-009 Observability baseline (in-app instrumentation).** Added `core/observability`
  (structlog JSON + PII redaction, OpenTelemetry tracing with env-gated OTLP, Prometheus `/metrics` RED
  + per-tenant + worker task metrics, env-gated Sentry) single-sourced across api/worker; request-context
  middleware correlates logs and adds `meta.request_id` + `X-Request-ID`. All backends no-op-safe when
  unset. 91 tests green, coverage 93 %, ruff/mypy-strict/import-linter clean. Live staging wiring deferred
  to **PV-003** (blocked on PV-002). Security review applied (see Security Review).

## Security Review (AI — security-reviewer)

Ran the `security-reviewer` agent over the logging/redaction, Sentry, request-id middleware, and
config paths (PII/secret-leakage focus). 9 findings; **no CRITICAL remains**. Disposition:

**Fixed in this story (code + tests):**
- **C-1 (CRITICAL) — Sentry shipped request bodies (login/refresh passwords) externally.** Added
  `max_request_body_size="never"` + a `before_send=_scrub_event` scrubber (drops request `data`/`cookies`
  and breadcrumb `data`). `sentry.py`.
- **H-1 (HIGH) — exception tracebacks bypassed redaction.** Added a `sanitize_exc_info` processor
  (runs after `format_exc_info`) that regex-scrubs `key=value` credential pairs, bearer tokens, and
  URL `user:pass@` creds from rendered `exc_info`/`stack` strings. `logging.py`.
- **H-2 (HIGH) — `SENSITIVE_KEYS` denylist gaps.** Reworked `redact_pii` to a normalised exact-set +
  substring scan (`token`/`secret`/`password`/`cookie`/`api_key`/…), catching `set-cookie`, `x-api-key`,
  `client_secret`, `new_password`, etc. **Deliberately excludes a bare `key`** so `run_key`/`cache_key`
  (legit job diagnostics) are not over-masked — covered by a regression test. `logging.py`.
- **H-3 (HIGH) — nested dict values leaked** (e.g. `headers={"authorization": …}`). Redaction now walks
  nested dicts to a bounded depth (3). `logging.py`.
- **H-4 (HIGH) — unvalidated client `X-Request-ID`** (log injection + unbounded size). Now accepted only
  if it matches `^[A-Za-z0-9._-]{1,128}$`, else a server UUID is used. `api/middleware.py`.
- **M-3 (MEDIUM) — JWT claims read outside the error guard** (crafted valid-signature token → unhandled
  `KeyError`/500). Claims extraction moved inside `try/except (KeyError, ValueError)` → `InvalidCredentials`.
  `api/deps.py`. (Also hardens code this story already touched for the tenant metric.)

**Deferred / documented (out of QV-009 scope, no new risk introduced here):**
- **M-1 (MEDIUM) — no startup guard rejecting the default weak `JWT_SECRET` in non-local envs.**
  Pre-existing (QV-006 config); belongs to **QV-079** (security hardening pass). Not added here to avoid
  scope creep and test ripple. Mitigated operationally: secrets come from Secrets Manager in staging/prod.
- **L-2/M-3-dup (MEDIUM) — `/metrics` is unauthenticated and carries a `tenant` label (tenant UUIDs).**
  Standard Prometheus model is network-level restriction; recorded as a **deploy requirement in PV-003**
  (must be scraper-only / not internet-routable), consistent with the worker metrics port.
- **L-1 (LOW) — free-text log message not scanned for embedded secrets.** Documented as an explicit
  Limitation in `logging.py`'s docstring + guideline (pass secrets as keyword args, never f-strings).

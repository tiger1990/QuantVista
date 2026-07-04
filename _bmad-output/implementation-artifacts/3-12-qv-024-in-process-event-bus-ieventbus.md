---
baseline_commit: 3348875ab19eebe6c9d6a3fdf08612669d2d151b
---

# Story 3.12: QV-024 — Event bus (IEventBus): in-process + Redis Streams + Kafka, config-toggled

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **the platform**,
I want **one `IEventBus` contract with three interchangeable backends — in-process, Redis Streams, and Kafka — selected by config**,
so that **producers and consumers are decoupled into an event-driven DAG, and we can toggle the transport by traffic (in-process when idle → Redis Streams → Kafka under load) with zero producer/handler/schema changes**.

> Canonical ID **QV-024** · Epic 3 (EPIC-DATA) · `[BE]` · 5pts (**expanded by user decision to all 3 backends now**) · Sprint 02 · depends: **QV-015 ✅**
> Authoritative: `plans/02` §7 ("Event bus from day one (in-process → Redis Streams). … the same handlers move to stream consumers on extraction."). Seam for `future-scale-microservices.md`.

## Locked decisions

- **User decision: build all three backends now (Option 3), config-toggled.** `InProcessEventBus`, `RedisStreamEventBus`, `KafkaEventBus` all implement the same `IEventBus` contract + envelope; `Settings.event_bus_backend` (`in_process` | `redis_streams` | `kafka`) selects one via the `get_event_bus()` factory. Local dev defaults to `in_process`; production toggles Redis Streams / Kafka by traffic. **Caveat (recorded):** Redis Streams + Kafka backends are validated here against **synthetic test handlers** (publish → consumer loop → handler receives the envelope), **not** a real domain consumer — the first real consumer is QV-025 (`compute_indicators`), which will exercise delivery/ordering for real. Partition/ordering/retention/DLQ tuning is deliberately minimal now and revisited when real load + consumers exist.
- **Same contract for all three.** `publish(topic, dict)` + `subscribe(topic, handler)` (the existing `IEventBus` Protocol, unchanged) + `start()`/`stop()` lifecycle on the async backends (no-op for in-process) for the consumer runtime. Handler signature `Callable[[dict], None]` receives the **envelope** — identical whether dispatched in-process or read from a stream/topic.
- **Reserved event envelope** (all backends): `{event_id (uuid4), occurred_at (iso8601 UTC), topic, version (int=1), payload (dict)}`. JSON is the wire format (Redis Streams field / Kafka message value) → replay, idempotency/dedup, DLQ, tracing are structurally ready. Producers keep `publish(topic, payload)`; the envelope is stamped in the bus.
- **Synchronous in-process; async (consumer-loop) for Redis/Kafka.** In-process `publish` dispatches inline. Redis Streams (`XADD` + consumer-group `XREADGROUP`/`XACK`, at-least-once) and Kafka (`producer.send` + `KafkaConsumer` group) dispatch from a background reader thread started by `start()`. All dispatch is **per-handler error-isolated** (one handler raising never blocks siblings or the producer; logged).
- **Backends are lazy + optional deps.** `redis` is already a core dep (used as Celery broker). Kafka uses **`kafka-python-ng`** (pure-Python, no C build → installs cleanly on macOS 12 + CI Linux) as an **optional extra** `[kafka]`, **lazy-imported** inside `KafkaEventBus` (like the yfinance dev adapter). Importing `core.events` never requires a running broker or the kafka lib.
- **Testing (skip-if-unavailable, mirrors the DB/promtool pattern).** In-process bus: unit-tested everywhere (CI + local). Redis Streams: integration test **skips if Redis is unreachable** (runs on the native Homebrew Redis locally; a `redis` service is added to the CI job so it runs in CI too). Kafka: integration test **skips if a broker is unreachable / `kafka-python-ng` absent** (runs locally against `~/kafka` — [[kafka-local-feasibility]]; **not** run in CI — no Kafka service). `get_event_bus()` singleton isolated via `reset_event_bus()`.
- **`core` stays the DAG foundation.** All buses + event types live in `core` (imported by all contexts, importing none). `LoggingEventBus` retained; the shared default becomes the configured backend via `get_event_bus()`.

## Acceptance Criteria

1. **One contract, three backends.** `InProcessEventBus`, `RedisStreamEventBus`, `KafkaEventBus` each satisfy `IEventBus` (`publish`/`subscribe`) + expose `start()`/`stop()`. `publish(topic, payload)` stamps + transports the envelope; `subscribe(topic, handler)` registers a handler that receives the envelope. Per-handler error isolation on all three (`publish`/dispatch never propagates a handler error).
2. **Config toggle.** `Settings.event_bus_backend: str = "in_process"` (env-driven). `get_event_bus()` returns the process-singleton bus for the configured backend: `in_process` → `InProcessEventBus`; `redis_streams` → `RedisStreamEventBus`; `kafka` → `KafkaEventBus`; unknown → `ValueError`. `reset_event_bus()` clears the singleton (tests).
3. **Envelope.** Every delivered event is `{event_id (uuid4 str, unique per publish), occurred_at (iso8601 UTC), topic, version (int), payload (dict)}` — identical shape across all three backends. Round-trips through Redis Streams / Kafka JSON unchanged.
4. **Typed domain events.** Frozen dataclasses with `TOPIC`/`VERSION` ClassVars + `to_payload()`/`from_payload()` for: `PricesIngested`, `PricesValidated`, `FundamentalsUpdated`, `IndicatorsComputed`, `FactorsComputed`, `ScoresComputed`, `NewsScored`. JSON-safe payloads; `from_payload(e.to_payload()) == e`.
5. **In-process (sync).** `publish` dispatches inline to all handlers for the topic (subscription order); multiple handlers; no-handler = no-op (logged). Shared singleton via `get_event_bus()`.
6. **Redis Streams (async, at-least-once).** `publish` → `XADD topic * data <json-envelope>`. `start()` creates the consumer group(s) + a background reader (`XREADGROUP` → dispatch → `XACK`); `stop()` joins it. A subscribed handler receives the published envelope. Verified against a live Redis (skip if unreachable).
7. **Kafka (async).** `publish` → `KafkaProducer.send(topic, <json-envelope-bytes>)`. `start()` runs a `KafkaConsumer` (group) background reader → dispatch; `stop()` closes it. A subscribed handler receives the envelope. Verified against a live broker `~/kafka` (skip if unreachable / lib absent). `kafka-python-ng` lazy-imported.
8. **Producers wired.** `jobs/ingest.py` + `jobs/quality.py` publish through `get_event_bus()` (not a throwaway `LoggingEventBus`). Emitted topics/payloads unchanged on the wire (envelope wraps them). `market_data`/DAG boundaries unchanged (`lint-imports` green).
9. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80% coverage on new in-process + factory + event-type code (Redis/Kafka backends covered by skip-if-available integration tests). CI stays green (Redis service added; Kafka tests skip in CI). `[kafka]` optional extra added.

## Tasks / Subtasks

- [x] **Task 1 — envelope + InProcessEventBus + factory/toggle** (AC: #1, #2, #3, #5)
  - [x] `core/events.py`: `Handler`, `build_envelope(topic, payload, version=1)`, `InProcessEventBus` (sync dispatch, error-isolated, `subscribe`, no-op `start/stop`), keep `LoggingEventBus`. `Settings.event_bus_backend` (`core/config.py`). `get_event_bus()` factory + `reset_event_bus()` singleton. Unit tests: dispatch/envelope/isolation/no-op/singleton/factory-raises-on-unknown.
- [x] **Task 2 — typed domain events** (AC: #4)
  - [x] `core/event_types.py`: frozen dataclasses (`TOPIC`/`VERSION`/`to_payload`/`from_payload`) for the 7 events; round-trip unit tests.
- [x] **Task 3 — RedisStreamEventBus** (AC: #6)
  - [x] `core/events.py` (or `core/event_backends.py`): `RedisStreamEventBus(redis_url, group, consumer)` — `publish` `XADD` json envelope; `subscribe`; `start()` (ensure group via `XGROUP CREATE MKSTREAM`, spawn daemon reader thread `XREADGROUP`→dispatch→`XACK`); `stop()` (flag + join). Integration test (skip if Redis down): subscribe handler, start, publish, poll for receipt, assert envelope, stop; error isolation.
- [x] **Task 4 — KafkaEventBus** (AC: #7)
  - [x] `KafkaEventBus(bootstrap_servers, group)` — lazy `import kafka`; `publish` producer.send json; `subscribe`; `start()` (KafkaConsumer group daemon reader → dispatch); `stop()` (close). `[kafka]` extra (`kafka-python-ng`). Integration test (skip if broker/lib absent): round-trip against `~/kafka`.
- [x] **Task 5 — wire producers + CI + gates + reconcile** (AC: #8, #9)
  - [x] `jobs/ingest.py` (`_run`/`_run_corpactions`/`_run_fundamentals`) + `jobs/quality.py` (`_run_validate`): construct services with `get_event_bus()`. `.github/workflows/ci.yml`: add a `redis` service to `backend-rls` (so Redis Streams tests run in CI). Run all gates locally + against native Redis + `~/kafka`. Reconcile QV-023 → done (already applied on this branch).

## Dev Notes

### Scope discipline
QV-024 = the full event-bus stack: one `IEventBus` contract + envelope + typed events + **three backends** (in-process / Redis Streams / Kafka) + config toggle + producer wiring. **Not this story:** the first real consumer (`compute_indicators` → QV-025, subscribes to `PricesValidated`), cache-invalidation/alerts consumers (Epic 4/5), production tuning of partitions/ordering/retention/DLQ (revisited under real load), a managed Kafka/Redis in staging (infra). **No schema/migration** (events are transient). **Caveat:** Redis/Kafka backends validated with synthetic handlers until QV-025.

### Backend shapes
```
InProcessEventBus   publish → for h in handlers[topic]: h(envelope)          (sync, singleton)
RedisStreamEventBus publish → XADD topic * data=<json>                        (async)
                    start() → XGROUP CREATE; thread: XREADGROUP→h(env)→XACK
KafkaEventBus       publish → producer.send(topic, <json-bytes>)              (async)
                    start() → thread: KafkaConsumer(group).poll→h(env)
```
- Envelope is one JSON blob (`data` field / message value) → avoids nested-map quirks; language-independent; versionable.
- Error isolation everywhere: a raising handler is logged (`event_handler_failed`, topic, event_id) + skipped; producer + siblings unaffected.
- Lifecycle: async backends need `start()` (reader thread) before delivery + `stop()` (graceful join/close). In-process `start/stop` = no-op. The worker composition root calls `start()` at boot when the backend is async (QV-025 wiring); tests call it explicitly.

### Toggle + local verifiability ([[kafka-local-feasibility]])
`Settings.event_bus_backend` selects the backend; all three are **locally runnable**: in-process (always), Redis Streams (native Homebrew Redis), Kafka (`~/kafka`, KRaft, Zulu JDK 21). So each backend is smoke-tested here; CI runs in-process + Redis (service added), Kafka skips in CI (no broker) — same skip-if-unavailable pattern as the DB/promtool tests.

### Deps
- `redis` — already core (Celery broker). Reuse for `RedisStreamEventBus`.
- `kafka-python-ng` — new **optional** extra `[kafka]`, pure-Python (installs on macOS 12 + CI Linux, no librdkafka C build). Lazy-imported in `KafkaEventBus`; a clear error if the extra is missing and backend=kafka.

### Boundaries & gates
- All buses + event types in `core` (imports only stdlib/redis/structlog + lazy kafka); `core` imports no bounded context → `lint-imports` 3/3. `IEventBus` Protocol unchanged (publish/subscribe) → no fake-bus churn; `start/stop` are concrete-class methods.
- mypy `--strict`: `Handler` alias, `ClassVar`, frozen `@dataclass(slots=True)`, JSON-safe payloads, lazy-import typed via `TYPE_CHECKING`. Coverage ≥ 80% on in-process + factory + event types (Redis/Kafka via skip-if-available integration).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; RED→GREEN per task)

### Debug Log References

- Verified against local **PostgreSQL 18.4** + native **Redis 7** + **Kafka 4.3.1** (`~/kafka`, KRaft, Zulu JDK 21 — [[kafka-local-feasibility]]).
- Final gates (with **both Redis and Kafka brokers live**): `ruff` + `ruff format --check` clean ·
  `mypy` (strict) Success (116 files) · `lint-imports` 3 kept/0 broken (`core` imports no context) ·
  `pytest` → **244 passed, 3 skipped** (only the 3 promtool tests; the Kafka test **runs** with the
  broker up). Coverage **96 %**; new: `core/config.py` 100 %, `core/event_types.py` 100 %,
  `core/events.py` **93 %**.
- **All three backends proven locally this session against LIVE brokers:** in-process (unit),
  **Redis Streams** (native Redis — publish→consumer-group→handler + error isolation), **Kafka** (live
  `~/kafka` broker started for the final pass — publish→consumer-group→handler). The Kafka test skips only
  when its broker is unreachable (= CI, no Kafka service).
- **Coverage bumps applied** (per review): added `[tool.coverage.run] concurrency = ["thread"]` so the
  Redis/Kafka **reader-thread `_run`** bodies are counted (69 % → 91 %), plus factory-selects-backend and
  `LoggingEventBus.publish` tests (91 % → **93 %**). The remaining 11 uncovered `events.py` lines are
  **defensive error branches** (Redis `BUSYGROUP` handling, the reader-thread `except` recovery paths) +
  one no-op `return` — intentionally not forced. No coverage `fail_under` gate.

### Completion Notes List

- **One `IEventBus` contract, three config-toggled backends (user Option 3).** `InProcessEventBus` (sync),
  `RedisStreamEventBus` (`XADD` + consumer-group `XREADGROUP`/`XACK`, at-least-once), `KafkaEventBus`
  (`KafkaProducer` + `KafkaConsumer` group). `Settings.event_bus_backend` (`in_process` | `redis_streams`
  | `kafka`) selects via `get_event_bus()` (process singleton; unknown → `ValueError`). Flip the transport
  by traffic with **zero** producer/handler/schema change.
- **Reserved envelope** on every event: `{event_id (uuid4), occurred_at (iso8601 UTC), topic, version,
  payload}` — JSON on the wire for all three transports → replay / idempotency / DLQ / tracing are ready.
- **Typed domain events** (`core/event_types.py`, 100 % cov): `PricesIngested`, `PricesValidated`,
  `FundamentalsUpdated`, `IndicatorsComputed`, `FactorsComputed`, `ScoresComputed`, `NewsScored` — frozen
  dataclasses, `TOPIC`/`VERSION` + `to_payload`/`from_payload` round-trip, JSON-safe.
- **Error isolation** on all backends: a raising handler is logged + skipped; never blocks siblings or the
  producer. Sync in-process; async (reader thread via `start()`/`stop()`) for Redis/Kafka.
- **Producers wired** to `get_event_bus()` (`jobs/ingest.py` prices/corp-actions/fundamentals,
  `jobs/quality.py`, `jobs/universe.py`) — one-line swaps (services already inject the bus). End-to-end
  proven: `DataQualityService(get_event_bus())` → subscriber receives `PricesValidated`.
- **Caveat (recorded, per the user):** the Redis/Kafka backends are validated with **synthetic test
  handlers** — the first real domain consumer is QV-025 (`compute_indicators` on `PricesValidated`), which
  will drive real delivery/ordering; partition/retention/DLQ tuning is deliberately minimal until then.
- **Deps + CI:** `kafka-python-ng` added as the **optional `[kafka]` extra** (pure-Python, lazy-imported —
  default install never needs it); mypy override for `kafka`. A **`redis:7` service** added to the CI
  `backend-rls` job so the Redis Streams test runs in CI; Kafka skips in CI (no broker). **No
  security-reviewer** — internal transport, no auth/PII/user-input. **No migration.**

### File List

**New**
- `backend/src/quantvista/core/event_types.py` — 7 typed domain events.
- `backend/tests/test_event_bus.py` — in-process bus + envelope + factory (unit).
- `backend/tests/test_event_types.py` — event round-trips.
- `backend/tests/integration/test_event_bus_redis.py` — RedisStreamEventBus (live Redis, skip-if-down).
- `backend/tests/integration/test_event_bus_kafka.py` — KafkaEventBus (live broker, skip-if-down/lib-absent).
- `backend/tests/integration/test_event_bus_wiring.py` — producer → shared bus → subscriber.

**Modified**
- `backend/src/quantvista/core/events.py` — `InProcessEventBus` / `RedisStreamEventBus` / `KafkaEventBus`
  + `build_envelope` + `get_event_bus`/`reset_event_bus` factory; `LoggingEventBus` retained.
- `backend/src/quantvista/core/config.py` — `event_bus_backend` / `event_bus_group` / `kafka_bootstrap_servers`.
- `backend/src/quantvista/jobs/{ingest,quality,universe}.py` — producers publish via `get_event_bus()`.
- `backend/pyproject.toml` — `[kafka]` extra + mypy override for `kafka`.
- `.github/workflows/ci.yml` — `redis:7` service on `backend-rls`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-024 status; QV-023 → done (housekeeping).

### Change Log

- **2026-07-04 — QV-024 event bus: in-process + Redis Streams + Kafka, config-toggled.** Built one
  `IEventBus` contract + reserved envelope + 7 typed events + three backends selected by
  `Settings.event_bus_backend`; wired producers to the shared bus. All three proven locally (Redis on
  native Redis, Kafka on `~/kafka`); CI runs in-process + Redis (service added), Kafka skips. Redis/Kafka
  validated with synthetic handlers until QV-025's real consumer. `kafka-python-ng` optional `[kafka]`
  extra. 244 tests green / 3 skipped (Kafka test verified against a live `~/kafka` broker), coverage 96 %
  (`events.py` 93 % with `concurrency=thread`); ruff/mypy-strict/import-linter clean. No migration.

---
baseline_commit: c1be88385aeebf9c481f73dad0a9765a870acde9
---

# Story 4.4: QV-031 — Caching + invalidation on ScoresComputed

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **a user**,
I want **fast score/ranking reads backed by Redis, invalidated the moment scores recompute**,
so that **the dashboard is snappy and never serves stale rankings**.

> Canonical ID **QV-031** · Epic 4 (EPIC-INTEL) · `[BE]` · 3pts · Sprint 03 · depends: **QV-030 ✅** (`ScoresComputed`)
> Authoritative: `03` §8 (cache table: `score:{market}:{date}`, `rank:{universe}:{date}`, `stock:{id}:detail`; invalidate on `ScoresComputed`; TTL backstop). The read API that consumes this is **QV-032**.

## Locked decisions

- **Cache-aside, not write-through.** A read populates the cache (`rank:{market}:{date}`); the **`ScoresComputed` event invalidates** it; a **TTL backstop** bounds staleness if an event is ever missed (`03` §8). Reads never block on the cache being warm.
- **`ICache` seam + `RedisCache` + `NullCache`** (`core/cache.py`, foundation — mirrors the event-bus pattern). `RedisCache` lazy-connects (`redis.Redis.from_url`, JSON values, per-key TTL); `NullCache` is a no-op (returned when `cache_enabled=false` or Redis absent, so dev/tests work with no Redis). `get_cache()` is a config-driven singleton (`reset_cache()` for tests). No hard Redis dependency at import.
- **Scope = scores/rankings cache + invalidation** (the AC's primary). `rankings_for(session, market, date)` (scores ordered by `composite_score` desc) + a cache-aside read-through. The **`stock:{id}:detail` cache lands with QV-032** (it needs that story's stock-detail read); screener/entitlement caches are their own stories. Noted, not built here.
- **Invalidation consumer on the shared bus.** `on_scores_computed(env)` deletes `rank:{market}:{date}` + `score:{market}:{date}`; registered in `register_pipeline_consumers` beside the pipeline consumers (fires when QV-030's `compute_scores` emits `ScoresComputed`). Payload carries `universe` (= market) + `date`.
- **Config:** `cache_enabled: bool = True`, `cache_ttl_seconds: int = 3600` (1h backstop). Redis via the existing `redis_url`. CI already runs a `redis:7` service (QV-024) → the `RedisCache` integration tests execute in CI.
- **Placement:** `core/cache.py` (foundation); `rankings_for` + cache-aside in `analytics`; the invalidation consumer in `jobs`. Global read → privileged/read session. **No migration.**

## Acceptance Criteria

1. **`ICache` + `RedisCache` + `NullCache`.** `get(key) -> Any | None`, `set(key, value, ttl_seconds=None)`, `delete(*keys)`. `RedisCache` round-trips JSON-serialisable values with TTL; `NullCache` is a no-op (get→None). `get_cache()` returns `RedisCache` when `cache_enabled` else `NullCache`; lazy connect (no Redis import at module load).
2. **Rankings read-through (cache-aside).** `rankings_for(session, market, date) -> list[dict]` (symbol + scores, ordered by composite desc). A cache-aside helper returns the cached value on hit, else reads the DB, caches it under `rank:{market}:{date}` with the TTL, and returns it.
3. **Invalidation on `ScoresComputed`.** `on_scores_computed` deletes the `rank:{market}:{date}` + `score:{market}:{date}` keys; subscribed via `register_pipeline_consumers`. A published `ScoresComputed` → the keys are gone.
4. **TTL backstop.** Cached entries expire after `cache_ttl_seconds` even with no event (proven by a short-TTL test).
5. **Boundaries.** `core/cache.py` imports stdlib + lazy redis; `analytics` uses the cache via the `ICache` seam; the consumer in `jobs`. `analytics` imports no `jobs`. `lint-imports` green. **No migration.**
6. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80 % coverage. **Unit:** `NullCache` no-ops; the cache-aside helper (hit skips DB, miss populates) with a fake cache; the invalidation consumer deletes the right keys (fake cache). **Integration** (real Redis — CI has the service; local native Redis): `RedisCache` get/set/delete + TTL expiry; end-to-end `compute_scores → ScoresComputed → rank key invalidated` (real Postgres + Redis).

## Tasks / Subtasks

- [x] **Task 1 — `ICache` + `RedisCache` + `NullCache`** (AC: #1)
  - [x] `core/cache.py` (new): `ICache` Protocol; `RedisCache(url)` (lazy `redis.Redis.from_url`, `decode_responses`, JSON dumps/loads, `setex` for TTL, `delete(*keys)`); `NullCache`; `get_cache()`/`reset_cache()` singleton driven by `cache_enabled`. `core/config.py`: `cache_enabled`, `cache_ttl_seconds`.
- [x] **Task 2 — rankings read-through** (AC: #2)
  - [x] `analytics/repositories.py`: `rankings_for(session, market, date) -> list[dict]` (join `scores`+`stocks`, order by `composite_score` desc). `analytics/services.py`: `cached_rankings(cache, session, market, date)` — cache-aside under `rank:{market}:{date}` + TTL.
- [x] **Task 3 — invalidation consumer** (AC: #3)
  - [x] `jobs/consumers.py`: `on_scores_computed(env)` → `get_cache().delete("rank:{m}:{d}", "score:{m}:{d}")`; subscribe `"ScoresComputed"` in `register_pipeline_consumers`.
- [x] **Task 4 — tests + gates + reconcile** (AC: #6)
  - [x] Unit: `NullCache`; cache-aside hit/miss (fake cache); consumer invalidation (fake cache). Integration (`tests/integration/test_cache.py`, real Redis): `RedisCache` round-trip + delete + short-TTL expiry; end-to-end scores→ScoresComputed→invalidated. Skip Redis integration gracefully if Redis absent (like the DB `@pytest.mark.integration`). Run gates; reconcile QV-030 → done (already applied).

## Dev Notes

### Cache-aside flow (03 §8)
```
read rankings ─▶ cache.get(rank:{market}:{date})
                    ├─ hit  ─▶ return
                    └─ miss ─▶ rankings_for(DB) ─▶ cache.set(..., ttl) ─▶ return
compute_scores ─▶ ScoresComputed ─▶ on_scores_computed ─▶ cache.delete(rank:…, score:…)
TTL backstop: entries expire after cache_ttl_seconds even if an event is missed.
```

### Reuse map
- Redis lazy-import pattern + `redis.Redis.from_url(decode_responses=True)` — mirror `RedisStreamEventBus` (`core/events.py`). `redis_url` config already present; CI `redis:7` service already wired (QV-024).
- `register_pipeline_consumers` + thin-consumer pattern (QV-025/030); `get_cache()` singleton mirrors `get_event_bus()`/`reset_event_bus()`.
- `scores` table (QV-029) — `rankings_for` reads it; the `ScoresComputed` payload (`universe`, `date`) — the invalidation key source.
- `@pytest.mark.integration` + graceful skip when the backend is absent (Redis here, Postgres elsewhere).

### Boundaries & gates
- `core/cache.py` = foundation (imports stdlib + lazy redis; imports no domain context). `analytics` consumes `ICache` (no `jobs`/`api`). Consumer in `jobs` (composition root). `lint-imports` 3/3. Coverage ≥ 80 % on cache + read-through + consumer. **Not this story:** the HTTP read endpoint (QV-032), `stock:{id}:detail`/screener/entitlement caches, stale-while-revalidate on the frontend.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- Verified against local **PostgreSQL 18.4** + **native Redis** (redis-cli PONG).
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (143 files) ·
  `lint-imports` 3 kept/0 broken (`core/cache.py` imports no domain context; `analytics` uses the `ICache`
  seam) · `pytest` → **292 passed, 4 skipped** (Kafka broker down + 3 promtool). Coverage 94 %; new:
  `analytics/services.py` **100 %**, `jobs/consumers.py` **100 %**, `core/cache.py` 87 %.

### Completion Notes List

- **Cache-aside rankings, event-invalidated, TTL-backstopped (`03` §8).** `ICache` seam (`core/cache.py`)
  with `RedisCache` (lazy connect, JSON values, `set(..., ex=ttl)`, `delete(*keys)`) + `NullCache` (no-op
  for dev/tests with no Redis). `get_cache()` config-driven singleton (`RedisCache` when `cache_enabled`,
  else `NullCache`) — no hard Redis import at load.
- **Read-through** (`analytics/services.cached_rankings`, 100 %): cache → `rankings_for` (DB) → cache under
  `rank:{market}:{date}` with the TTL. Unit-proven: a hit skips the DB read entirely (`rankings_for` called
  exactly once across two calls).
- **Invalidation consumer** (`jobs/consumers.on_scores_computed`, 100 %): deletes `rank:`/`score:{market}:{date}`
  on `ScoresComputed`; subscribed in `register_pipeline_consumers` beside the pipeline consumers → QV-030's
  `compute_scores` now auto-invalidates the cache.
- **Verified against real Redis** (`test_cache_redis.py`): JSON round-trip, delete, **TTL expiry** (`ex=1` →
  gone after 1.2 s with no event), and end-to-end `ScoresComputed → rank key invalidated` through the real
  client. Skips gracefully if Redis is absent; **CI runs the `redis:7` service** (QV-024) so these execute in CI.
- **Boundaries:** `core/cache.py` is foundation (lazy redis, no domain import); `analytics` consumes the
  `ICache` seam (no `jobs`/`api`); the consumer is in `jobs`. **No migration; no security-reviewer** (internal
  read cache, no auth/PII/user-input). **Not this story:** the HTTP read endpoint (→ QV-032), the
  `stock:{id}:detail`/screener/entitlement caches (their stories).

### File List

**New**
- `backend/src/quantvista/core/cache.py` — `ICache` seam, `RedisCache`, `NullCache`, `get_cache()`/`reset_cache()`.
- `backend/tests/test_cache.py` — NullCache, cache-aside read-through, invalidation consumer (unit, fake cache).
- `backend/tests/integration/test_cache_redis.py` — RedisCache round-trip/delete/TTL + end-to-end invalidation (real Redis).

**Modified**
- `backend/src/quantvista/core/config.py` — `cache_enabled` + `cache_ttl_seconds`.
- `backend/src/quantvista/analytics/repositories.py` — `rankings_for` (cacheable ranked-scores read).
- `backend/src/quantvista/analytics/services.py` — `cached_rankings` cache-aside + `rankings_cache_key`.
- `backend/src/quantvista/jobs/consumers.py` — `on_scores_computed` + `ScoresComputed` subscription.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-031 status; QV-030 → done (housekeeping).

### Change Log

- **2026-07-05 — QV-031 caching + invalidation on ScoresComputed.** Added a Redis cache-aside layer for
  scores/rankings (`03` §8): the `ICache` seam (`RedisCache` + `NullCache`, `get_cache()` singleton), a
  `cached_rankings` read-through under `rank:{market}:{date}` with a TTL backstop, and an
  `on_scores_computed` consumer that invalidates the keys the instant QV-030 emits `ScoresComputed`.
  Verified against real Redis (round-trip, delete, TTL expiry, end-to-end invalidation); skips gracefully
  when Redis is absent, runs in CI via the `redis:7` service. No migration. 292 tests green, coverage 94 %
  (services + consumer 100 %); ruff/mypy-strict/import-linter clean. The read API (QV-032) consumes this next.

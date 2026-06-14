# Future Plan — Service Extraction & Horizontal Scale

> **Status:** Deferred. v1 ships as a **modular monolith with explicit seams** (D4, `02`). This plan
> describes *when* and *how* to extract services — only when scale/organizational pressure justifies the ops
> cost. Premature extraction is a common, expensive mistake; the seams mean we can wait.

---

## 1. Triggers to extract (don't extract before these)

- A module's scaling profile diverges sharply (e.g., NLP/sentiment is CPU/GPU-bound and bursty while the API
  is I/O-bound) and co-scaling wastes money.
- Team topology: multiple squads stepping on one deploy cadence; independent release cycles needed.
- A bounded context needs independent availability/SLO or data-store specialization.
- The monolith approaches its vertical/throughput ceiling (target: ~10k tenants / 100k MAU first, `01`).

## 2. Extraction order (by likely payoff)

1. **News & Sentiment / NLP** — clearest divergent scaling; already on its own `nlp` queue.
2. **Analytics (scoring/backtesting)** — compute-heavy; can own a Parquet/DuckDB read path.
3. **Market Data ingestion** — vendor I/O isolation, independent retry/SLA.
4. **Portfolio/Risk & Alerts** — extract if user-facing load demands.
   Identity/Tenancy typically stays central (or becomes a shared auth service) longest.

## 3. How the seams make it incremental

Because modules already communicate only through interfaces and domain events (`02`):
- Replace an **in-process interface** call with an HTTP/gRPC client behind the *same* interface — callers
  don't change.
- Move an **in-process event handler** to a **Redis Streams** (or Kafka, if warranted) consumer — the event
  contract is unchanged.
- Carve the module's tables into its own schema/DB; keep reference data access via API or a read replica.
- Contract tests (already from the OpenAPI-first approach) guard the new network boundary.

## 4. Supporting infrastructure to add at extraction time

- Service-to-service auth (mTLS / signed tokens), service discovery, per-service deploys/Helm charts.
- Stronger event backbone (Kafka) if Redis Streams throughput/retention is exceeded.
- Distributed tracing already in place (OTel) — extend across services.
- Per-service SLOs, dashboards, on-call ownership.
- Saga/outbox pattern for cross-service consistency where a single DB transaction no longer spans the work.

## 5. Data scaling (parallel track, independent of service split)

- Postgres: read replicas, connection pooling (PgBouncer), partition pruning, archive cold partitions to
  Parquet (`03`).
- Hot reads already cached in Redis; consider materialized projections for rankings/screeners at very high
  read volume.
- Tenant isolation upgrade path: promote a large enterprise tenant to a dedicated schema/DB without affecting
  the shared pool (D6).

## 6. Anti-goals

- Don't split into microservices for resume value. Each service is a new failure domain, deploy pipeline, and
  on-call burden. Extract on evidence (the triggers in §1), one boundary at a time, measured before/after.

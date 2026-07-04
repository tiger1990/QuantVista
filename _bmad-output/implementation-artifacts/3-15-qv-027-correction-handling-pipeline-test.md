---
baseline_commit: 96bb60a115e31917894ff25f6cd9c3af28359f71
---

# Story 3.15: QV-027 — Correction-handling pipeline test

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **QA**,
I want **proof that data corrections self-heal — a fundamentals revision creates a new bitemporal version AND enqueues a downstream recompute for the affected dates**,
so that **revisions never leave stale derived data (scores/factors) silently wrong**.

> Canonical ID **QV-027** · Epic 3 (EPIC-DATA) · `[QUANT]` · 3pts · Sprint 02 (**last story**) · depends: **QV-022 ✅** (ingest fundamentals), **QV-025 ✅** (event consumers)
> Authoritative: `06` §5 — "**Correction handling:** a fundamentals revision inserts a new bitemporal version and enqueues `compute_factors`/`compute_scores` for affected dates → scores self-heal." · `06` §1 (Correctness over speed) · `03` §5 (bitemporal PIT).

## What exists vs. what QV-027 wires

| Self-heal step | Status before QV-027 |
|---|---|
| 1. Revision → new **bitemporal version** | ✅ **exists** — `record_fundamental_version` returns `"revised"` (close prior + insert new), QV-021 |
| 2. Revision **detected** → recompute **enqueued** for affected dates | ❌ **this story** — no consumer; `FundamentalsUpdated` carries only counts, not *which* stocks/dates |
| 3. Recompute re-runs `compute_factors`/`compute_scores` | ⛔ **Epic 4** — those tasks don't exist yet |

QV-027 wires **step 2** and tests **1 + 2** end-to-end. Step 3's real factor/score math is Epic 4 — it plugs into the `recompute_on_correction` seam this story creates.

## Locked decisions (owner-confirmed)

- **New `FundamentalsRevised` event (distinct from the every-run `FundamentalsUpdated`).** It fires **only when a revision occurs** and carries the affected filings: `{market, knowledge_time, revisions: [{stock_id, period_end, statement_type}]}` (JSON-safe). `FundamentalsUpdated` (counts) is unchanged. The revision is the specific "correction" signal that drives self-heal.
- **A QV-027-owned `recompute_on_correction(stock_id, period_end, statement_type)` seam task** — the documented **insertion point Epic 4 fills** with the real `compute_factors`/`compute_scores` call. It runs under `run_job` (`run_key = recompute:{stock_id}:{period_end}`, recorded in `jobs_runs`) and logs the correction intent, so the enqueue is **real + testable now** without pre-building Epic-4 tasks (YAGNI). No new event emitted (the recompute chain to scores is Epic 4).
- **"Affected dates" = the revised filing's `period_end`** (the seam carries `(stock_id, period_end)`; Epic 4 expands to the exact score dates that consumed the filing). Keeps this story honest and bounded.
- **Thin consumer enqueues the seam task** (QV-025 pattern): `on_fundamentals_revised(env)` → one `recompute_on_correction.delay(...)` per affected pair. Registered in `register_pipeline_consumers` beside the price consumers; heavy work stays in the worker.
- **No schema change, no migration.** Bitemporal `fundamentals` (QV-021) already versions revisions. Global tables → privileged engine. `market_data` stays a DAG leaf; the consumer + task are in `jobs` (composition root).

## Acceptance Criteria

1. **`FundamentalsRevised` event + service emission.** `FundamentalsIngestionService.ingest` collects the `(stock_id, period_end, statement_type)` of every filing that `record_fundamental_version` reports as `"revised"`, and — **only if ≥1 revision** — publishes `FundamentalsRevised` with them (alongside the existing `FundamentalsUpdated`). A revision-free run emits **no** `FundamentalsRevised`.
2. **`recompute_on_correction` seam task.** `recompute_on_correction(stock_id, period_end, statement_type)` under `run_job` (`recompute:{stock_id}:{period_end}`, recorded in `jobs_runs`); logs the correction; documented as the Epic-4 `compute_factors`/`compute_scores` insertion point. Idempotent-safe.
3. **Correction consumer wired.** `on_fundamentals_revised` subscribed via `register_pipeline_consumers`; a published `FundamentalsRevised` enqueues `recompute_on_correction.delay(...)` for **each** affected pair.
4. **The self-heal capstone test (real Postgres).** Ingest a filing (knowledge-time T0) → re-ingest a **revised** value for the same `(stock, period_end)` (T2) → assert: **(a)** a new bitemporal version — `fundamentals_as_of(T2)` returns the revised value while `fundamentals_as_of(T0)` still returns the original (PIT preserved, prior version closed); **(b)** `FundamentalsRevised` emitted on the 2nd run only, carrying the affected `(stock_id, period_end)`; **(c)** the consumer enqueues `recompute_on_correction` for that pair.
5. **Gates + tests.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` green; ≥80 % coverage on new code. Unit (consumer→enqueue, patched `.delay`) + integration (the capstone + the seam task under `run_job`).

## Tasks / Subtasks

- [x] **Task 1 — `FundamentalsRevised` event + service emission** (AC: #1)
  - [x] `core/event_types.py`: add `FundamentalsRevised` (`market, knowledge_time, revisions`).
  - [x] `market_data/services.py`: `FundamentalsIngestionService.ingest` collects revised `(stock_id, period_end, statement_type)`; publish `FundamentalsRevised` (JSON-safe payload) only when non-empty. `FundamentalsUpdated` unchanged.
- [x] **Task 2 — `recompute_on_correction` seam task** (AC: #2)
  - [x] `jobs/corrections.py` (new): `recompute_on_correction(stock_id, period_end, statement_type="quarterly")` under `run_job` (`recompute:{stock_id}:{period_end}`); structured log "correction_recompute" + docstring naming the Epic-4 `compute_factors`/`compute_scores` fill-in. Add `quantvista.jobs.corrections` to the mypy untyped-decorator override.
- [x] **Task 3 — correction consumer** (AC: #3)
  - [x] `jobs/consumers.py`: `on_fundamentals_revised(env)` → `recompute_on_correction.delay(...)` per revision; subscribe in `register_pipeline_consumers("FundamentalsRevised", …)`.
- [x] **Task 4 — tests** (AC: #4, #5)
  - [x] `tests/test_correction_consumer.py`: publish `FundamentalsRevised` on an `InProcessEventBus` with the consumer registered → assert `recompute_on_correction.delay` called per affected pair (patched).
  - [x] `tests/integration/test_correction_pipeline.py`: seed throwaway stock; a fake provider yields a filing then a revised value; drive `FundamentalsIngestionService.ingest` at T0 then T2 with a capturing bus → assert bitemporal PIT (as_of T0 vs T2), `FundamentalsRevised` on the 2nd run only with the affected pair, and (consumer) `recompute_on_correction` enqueued. Plus the seam task under `run_job` records `jobs_runs`. Cleanup by ids/run_key.
  - [x] Run all gates; reconcile QV-026 → done (already applied on this branch).

## Dev Notes

### Scope discipline
QV-027 = the **correction-detection → recompute-enqueue** wiring + its end-to-end self-heal proof. **Not this story:** the actual `compute_factors`/`compute_scores` math (**Epic 4**, plugs into `recompute_on_correction`); price-correction self-heal (prices already re-trigger `validate → compute_indicators` via QV-025 — fundamentals is the gap `06` §5 calls out); expanding "affected dates" beyond the filing's `period_end` (Epic-4 concern). **No migration.**

### The self-heal loop (what "done" looks like)
```
ingest_fundamentals (revised value, new knowledge_time)
   └─ record_fundamental_version → "revised"  (close prior open row, insert new open row — QV-021)
   └─ FundamentalsRevised {revisions:[(stock, period_end)]}
        └─ on_fundamentals_revised
             └─ recompute_on_correction.delay(stock, period_end)   ← Epic 4 fills compute_factors/scores
```

### Reuse map
- `record_fundamental_version` (returns `"inserted"/"revised"/"unchanged"`), `fundamentals_as_of(session, stock_id, as_of, statement_type=…)` — QV-021 bitemporal primitives.
- `FundamentalsIngestionService` (QV-022) — already loops filings + tallies `revised`; extend to **collect** the revised keys + emit `FundamentalsRevised`.
- `register_pipeline_consumers` + thin-consumer-enqueues-task pattern, `InProcessEventBus`, patched `.delay` — QV-024/025.
- `run_job`/`run_key`/`JobResult`/`JobRunLedger`, `@app.task(...)` — QV-015.
- Seed scaffold (throwaway market+stock, `T0/T2` knowledge-times, fake provider) — `test_fundamentals.py` / `test_fundamentals_ingest.py`.

### Boundaries & gates
- New event in `core` (leaf). Service change stays in `market_data` (leaf — publishes a dict on the injected bus, imports no consumer). Consumer + seam task in `jobs` (composition root) — add `quantvista.jobs.corrections` to the mypy untyped-decorator override. `lint-imports` 3/3. Coverage ≥ 80 % on the new consumer + task + service branch.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline; capstone test story)

### Debug Log References

- Verified against local **PostgreSQL 18.4**.
- Final gates: `ruff` + `ruff format --check` clean · `mypy` (strict) Success (129 files) ·
  `lint-imports` 3 kept/0 broken (`market_data` stays a leaf — the service publishes a dict on the
  injected bus, imports no consumer) · `pytest` → **265 passed, 4 skipped** (Kafka broker down + 3 promtool).
  Coverage 94 %; new: `core/event_types.py` **100 %**, `jobs/consumers.py` **100 %**, `jobs/corrections.py`
  83 % (uncovered = the daily Celery task body, tested via `_run_recompute`).

### Completion Notes List

- **Self-heal loop closed (`06` §5).** A fundamentals revision now propagates end-to-end:
  `record_fundamental_version → "revised"` → `FundamentalsRevised` (affected `(stock_id, period_end,
  statement_type)`) → `on_fundamentals_revised` → `recompute_on_correction.delay(...)`. The capstone test
  proves all three parts over real Postgres: PIT preserved (`as_of(T0)` = pe 10, `as_of(T2)` = pe 12),
  `FundamentalsRevised` emitted **on the revision run only** (not the initial insert), and exactly one
  recompute enqueued for the affected pair.
- **`FundamentalsRevised` event** (`core/event_types.py`, 100 %): distinct from the every-run
  `FundamentalsUpdated` (counts) — fires only when ≥1 revision, carries the affected filings. Producer-side
  typed dataclass; dict on the wire.
- **Service emission** (`market_data/services.py`): `FundamentalsIngestionService.ingest` collects the
  revised keys during the filing loop and publishes `FundamentalsRevised` only when non-empty. `market_data`
  stays a DAG leaf (publishes a dict on the injected `IEventBus`, imports no consumer).
- **`recompute_on_correction` seam** (`jobs/corrections.py`, 83 %): under `run_job`
  (`recompute:{stock_id}:{period_end}`, `jobs_runs` recorded), logs `correction_recompute`. This is the
  **Epic-4 insertion point** — `compute_factors`/`compute_scores` plug in here; the seam makes the enqueue
  real + testable now without pre-building Epic-4 tasks (YAGNI).
- **Consumer** (`jobs/consumers.py`, 100 %): `on_fundamentals_revised` fans out one recompute per affected
  filing; subscribed in `register_pipeline_consumers` beside the QV-025 price consumers (registered at worker
  start via `celery_app`). Thin — enqueues, heavy work in the worker.
- **No migration; no security-reviewer** (internal event wiring, no auth/PII/user-input). Epic 3 (EPIC-DATA)
  is complete with this story.

### File List

**New**
- `backend/src/quantvista/jobs/corrections.py` — `recompute_on_correction` seam task (Epic-4 insertion point).
- `backend/tests/test_correction_consumer.py` — consumer → recompute enqueue (unit, patched `.delay`).
- `backend/tests/integration/test_correction_pipeline.py` — the self-heal capstone + seam task under `run_job`.

**Modified**
- `backend/src/quantvista/core/event_types.py` — `FundamentalsRevised` event.
- `backend/src/quantvista/market_data/services.py` — collect revised keys + emit `FundamentalsRevised`.
- `backend/src/quantvista/jobs/consumers.py` — `on_fundamentals_revised` + subscription.
- `backend/pyproject.toml` — mypy untyped-decorator override for `quantvista.jobs.corrections`.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — QV-027 status; QV-026 → done (housekeeping).

### Change Log

- **2026-07-05 — QV-027 correction-handling pipeline test.** Closed the fundamentals self-heal loop
  (`06` §5): a revision now emits a new `FundamentalsRevised` event (affected `(stock, period_end)`), a
  `on_fundamentals_revised` consumer enqueues the QV-027-owned `recompute_on_correction` seam task (under
  `run_job`; the Epic-4 `compute_factors`/`compute_scores` insertion point), and the capstone integration
  test proves the whole chain over real Postgres — new bitemporal version + PIT preserved + revision-only
  emission + recompute enqueued for the affected pair. No migration. 265 tests green, coverage 94 %;
  ruff/mypy-strict/import-linter clean. **Completes Epic 3 (EPIC-DATA).**

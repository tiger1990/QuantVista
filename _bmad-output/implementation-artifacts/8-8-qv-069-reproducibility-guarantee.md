---
baseline_commit: 00e08e0415b7819ec0d20ca6038741b0c50cc232
---

# Story 8.8: QV-069 — Reproducibility guarantee

Status: done

**Epic:** EPIC-BT (Epic 8) · **Points:** 3 · **Depends:** QV-065 (`BacktestEngine`, `model_version`/`weights_version` stamping), QV-068 (metrics suite)

> **Same spec ⇒ same result, provably.** The engine is already a *pure function of PIT data* (QV-063–068) and stamps `model_version`/`weights_version` on every result; the spec is stored as validated JSONB (QV-062). This story **formalises** that into an auditable guarantee (`05` §4 point 7): a **`reproducibility_hash`** fingerprinting the *canonical spec + methodology versions* (so two runs of the same recipe are recognisably identical), a **permanent real-Postgres determinism guard** (run the same spec twice → byte-identical metrics), and a **persistence proof** (the succeeded row stores the full spec + both versions). **No schema/API change** — the hash rides in the existing `metrics` JSONB; the version columns already exist.

## Story

As a user, I want the same spec to yield the same result, so backtests are trustworthy.

## Acceptance Criteria

1. **Reproducibility fingerprint** — the engine stamps a stable **`reproducibility_hash`** into `metrics`: `sha256( canonical_spec_json | MODEL_VERSION | WEIGHTS_VERSION )`, where `canonical_spec_json = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",",":"))`. It is **identical** for the same spec + versions and **changes** if any spec field or version changes. Stamped on **both** the normal and degenerate (empty) paths (via the engine's `_stamp`).
   [Source: `05` §4 point 7; QV-065 `_stamp`/`MODEL_VERSION`/`WEIGHTS_VERSION`]

2. **Determinism — proven end-to-end** — a real-Postgres test seeds a synthetic universe and runs `BacktestEngine(BacktestDataAccess(session)).run(spec)` **twice with the same spec** → the two `metrics` dicts are **exactly equal** (every metric + `reproducibility_hash` + `model_version` + `weights_version`). This is the permanent guard against a determinism regression (a stochastic step, unordered iteration, or a floating-point path change would trip it).
   [Source: `05` §4 point 7 "re-running the same spec yields the same result"; QV-063/064 real-PG precedent]

3. **Stores the full spec + both versions** — a persistence proof: after the `run_backtest` job succeeds, the `backtests` row has (a) `spec` round-tripping the submitted spec (validated JSONB, unchanged), (b) the `model_version` **and** `weights_version` **columns** populated (already written by QV-065's `mark_succeeded`), and (c) `metrics` carrying `reproducibility_hash` + both versions. Assert via the real job + a row read.
   [Source: `analytics/backtests.py` (`mark_succeeded` version columns; `create_backtest` spec); QV-062 lifecycle]

4. **Deterministic hash — unit-proven** — pure-Python unit tests for the hash helper: identical spec → identical hash; a changed spec field (e.g. `top_n`, `rebalance`, `costs_bps`, date) → different hash; key-order / whitespace irrelevance (canonicalisation). No DB.
   [Source: standard content-hash discipline; determinism is cardinal for Epic 8]

5. **No schema / API change; gates green** — the hash lives in `metrics` (`jsonb`/`dict[str, Any]`), the version columns already exist — **no migration, no response-model change** (it surfaces via `response.metrics`). numpy/hashlib/json only. Full-tree gates green (ruff, ruff format, **bare `mypy`**, lint-imports **3/3**, bandit, pip-audit); ~100% coverage on the new helper. Existing bias/metrics/api/engine suites keep passing (the metrics dict only grows by one key).
   [Source: testing rules; QV-066 bias guards compare metrics dicts — a new key is additive]

---

## Dev Notes

### Placement & DAG

- **`analytics/backtest.py`** (UPDATE) — add a module-level `_reproducibility_hash(spec: BacktestSpec) -> str` (`hashlib.sha256` over the canonical spec JSON + `MODEL_VERSION` + `WEIGHTS_VERSION`); extend `_stamp` to take the `spec` and set `metrics["reproducibility_hash"]` alongside the two versions. `run` already calls `_stamp` on both branches — thread the `spec` through. No new module, no DAG change (`lint-imports` 3/3). `json`/`hashlib` are stdlib.
- **No changes** to the rebalance loop, metrics math (QV-068), the seams, the repo, the schema, or the routes. The hash is *derived from inputs the engine already has*.
- Python 3.13, mypy strict — **run bare `mypy`**.

### Reuse — do NOT re-implement / do NOT break

- **The engine is already deterministic** (QV-063–068: pure PIT reads, sorted tie-breaks, fixed iteration). QV-069 does **not** add determinism — it *proves + fingerprints* it. Do not "fix" anything in the loop.
- **`_stamp` already stamps `MODEL_VERSION`/`WEIGHTS_VERSION`** on both paths (QV-068) — extend it, don't duplicate. Signature becomes `_stamp(metrics, spec)`.
- **The version columns already persist** — `mark_succeeded(..., model_version=…, weights_version=…)` writes them (QV-065). The row's `metrics` also carries them (engine-stamped). QV-069 just asserts this; it does not change persistence.
- **Canonical spec** = `spec.model_dump(mode="json")` (the validated Pydantic model, dates as ISO strings) → `json.dumps(..., sort_keys=True, separators=(",",":"))`. This matches the **stored** JSONB (QV-062 persists `model_dump(mode="json")`), so the hash is stable across store/reload.

### Why a hash (not just "it's deterministic")

Determinism makes re-runs match; the **hash makes that auditable** — a user (and the QV-071 UI) can see at a glance that two backtests used the identical recipe (spec + methodology), and any silent methodology bump (`MODEL_VERSION`/`WEIGHTS_VERSION`) changes the fingerprint. It is the concrete artifact of "stores full spec + versions".

### Test shape

- **Unit** `tests/test_reproducibility.py`: `_reproducibility_hash` — same spec → same; changed `top_n`/`rebalance`/`costs_bps`/`start` → different; equivalent-but-reordered spec dict → same (canonicalisation). Optionally monkeypatch `MODEL_VERSION` → hash changes.
- **Integration** `tests/integration/test_backtest_reproducibility.py` (real PG, `@pytest.mark.integration`): seed a synthetic universe (reuse `test_backtest_engine_run.py`'s `daily_prices`/index seeding), run the engine **twice** with the same spec → `assert m1 == m2`; assert `reproducibility_hash`/`model_version`/`weights_version` present.
- **Persistence**: extend `tests/integration/test_api_backtests.py::test_submit_poll_run_lifecycle` to also assert `metrics` has `reproducibility_hash` + `model_version` + `weights_version`, and (raw SELECT) the row's `model_version`/`weights_version` **columns** are populated + `spec` round-trips.

### Scope boundary

- **Fingerprint + guard only.** No "verify this backtest" endpoint, no re-run-and-diff job, no content-hash *cache* (that's the `03` §7 derived-computation cache — a separate future item). The **Methodology & Disclaimer page** that surfaces reproducibility to users is QV-070 (`[PROD]`); the **UI** is QV-071.
- Do not add `reproducibility_hash` as a DB column (no migration) — it's a pure function of the stored `spec` + versions, so it's derivable + lives in `metrics`.

### Previous-story / epic intelligence

- **QV-068 (PR #77)** moved metrics into `analytics/backtest_metrics.py` and added `_stamp(metrics)` that sets `model_version`/`weights_version` on both the normal and empty paths — extend it to `_stamp(metrics, spec)` + the hash. `run` computes/returns via `compute_metrics`/`empty_metrics` then `_stamp`.
- **QV-066** bias guards assert `metrics` equality (no-look-ahead: unchanged; teeth: changed) — the new `reproducibility_hash` is a pure function of the spec, so it does **not** vary with the trap (same spec) and won't break those equality/inequality assertions. Confirm they stay green.
- Determinism + Decimal-as-string are cardinal; `_stamp` runs after the float→str metrics are built.

### Git intelligence (recent)

`00e08e0 QV-068 #77` · `4cc77ae QV-067 #76` · `00…065`. `analytics/backtest.py` `run`/`_stamp` is the only source touched; `test_backtest_engine_run.py` (QV-065) is the seeding template for the integration determinism test; `test_api_backtests.py` for the persistence assertion.

### Project context reference

`_bmad-output/project-context.md` — `backend/src/quantvista/<context>/`; determinism + PIT correctness are cardinal for Epic 8; money as `Decimal` via `str`. `05` §4 point 7 reproducibility.

## Tasks / Subtasks

### Task 1: Reproducibility hash (AC-1)
- [x] `analytics/backtest.py`: `_reproducibility_hash(spec)` = `sha256(canonical_spec_json | MODEL_VERSION | WEIGHTS_VERSION)`; extended `_stamp(metrics, spec)` to set `reproducibility_hash`; threaded `spec` into both `_stamp` calls (normal + degenerate) in `run`. `json`/`hashlib` stdlib.

### Task 2: Unit tests for the hash (AC-4)
- [x] `tests/test_reproducibility.py` (10 tests): hex-sha256 shape; same spec → same; canonicalisation ignores key order; each of `rank_by`/`top_n`/`rebalance`/`costs_bps`/`start`/`end` change → different; `MODEL_VERSION` bump (monkeypatched) → different.

### Task 3: End-to-end determinism guard (AC-2)
- [x] `tests/integration/test_backtest_reproducibility.py`: runs the real engine over NIFTY200 twice with the same spec → `assert m1 == m2` (byte-identical, no seeding needed — read-only, robust to data state); a changed spec → a different `reproducibility_hash`.

### Task 4: Persistence proof (AC-3)
- [x] `test_api_backtests.py::test_reproducibility_persisted`: after `run_backtest`, `metrics` carries `reproducibility_hash` + both versions; raw SELECT confirms the row's `model_version`/`weights_version` **columns** are populated and `spec` round-trips (`rules.top_n`, `start`).

### Task 5: Gates (AC-5)
- [x] Full-tree gates green (ruff, format, mypy 278, lint-imports 3/3, bandit, pip-audit); `backtest.py` 100%; **no migration/API change**. Story → review; sprint-status → review; Dev Agent Record filled.

## Dev Agent Record

### Debug Log

- RED: `tests/test_reproducibility.py` first failed on `ImportError` (helper missing) — confirming the tests drive the code.
- **Hash reads the module globals at call time** so the version-bump test can `monkeypatch.setattr(engine, "MODEL_VERSION", …)` and observe a different hash — no capture-at-import.
- **Canonicalisation is free:** `spec.model_dump(mode="json")` normalises the validated Pydantic model (defaults filled, dates → ISO), then `json.dumps(sort_keys=True)` — so a reordered input dict yields the same hash, and it matches the stored JSONB (QV-062 persists the same `model_dump`).
- **Bias guards unaffected:** the new `reproducibility_hash` is a pure function of the *spec*, so it's constant across the QV-066 trap injection (same spec) — the no-look-ahead equality + teeth-inequality assertions stay green (verified).
- Coverage: `backtest.py` reached 100% (the hash + both `_stamp` branches — the degenerate path via the existing `test_degenerate_range_returns_zeroed_metrics`).

### Completion Notes List

- **Reproducibility formalised, not re-invented.** The engine was already deterministic (QV-063–068) and stamped `model_version`/`weights_version`; QV-069 adds the auditable **`reproducibility_hash`** (`metrics`), a **permanent real-PG determinism guard** (same spec twice → byte-identical metrics), and a **persistence proof** (row stores full spec + both version columns).
- **No schema / API / migration:** the hash rides in the existing `metrics` JSONB (surfaced via `response.metrics`); the version columns already existed (QV-065). Only `analytics/backtest.py` changed in `src`.
- Scope held: fingerprint + guard only — no verify-endpoint, no re-run-diff job, no content-hash *cache* (the `03` §7 item), no DB column for the hash.
- Full suite **762 passed / 5 skipped**; all gates green.

### File List

- `backend/src/quantvista/analytics/backtest.py` (modified — `_reproducibility_hash`, `_stamp(metrics, spec)` + hash, `run` threads `spec`)
- `backend/tests/test_reproducibility.py` (new — 10 pure-unit hash tests)
- `backend/tests/integration/test_backtest_reproducibility.py` (new — real-PG determinism guard)
- `backend/tests/integration/test_api_backtests.py` (modified — `test_reproducibility_persisted`)

### Change Log

- 2026-07-28 — QV-069 reproducibility guarantee: `reproducibility_hash` (sha256 of the canonical spec + `MODEL_VERSION`/`WEIGHTS_VERSION`) stamped into `metrics`; permanent real-PG determinism guard (same spec → byte-identical metrics) + persistence proof (row stores full spec + both version columns). No schema/API change; `backtest.py` 100% covered; gates green.

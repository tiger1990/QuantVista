---
baseline_commit: f5b63e3d302ec9f7b5a33864d87c944888ec6b9a
---

# Story 4.10: QV-037 — Leakage/PIT regression test for scoring

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As **QA**,
I want **a guard against look-ahead bias in scoring**,
so that **credibility is protected permanently**.

> Canonical ID **QV-037** · Epic 4 (EPIC-INTEL) · `[QUANT]` · 3pts · Sprint 03 · depends: **QV-030 ✅** (compute_factors/scores)
> Authoritative: `05` §1.1 (structural bias defence) — companion to backtest bias tests (`05` §4). **US-02** credibility guard.

## What exists (and the gap QV-037 fills)

- **`tests/integration/test_factor_pit.py` (QV-028)** proves **factor-level** PIT: an individual `PEFactor`/`Return6MFactor` at an `as_of` ignores a later-knowledge restatement (bitemporal) and a future-dated indicator (`date <= as_of`). Good — but it asserts *per-factor*, not the *whole scoring pipeline*.
- **`ScoringContext`** (`analytics/context.py`) is the structural defence: `fundamentals_as_of` (knowledge-time = end of the `as_of` day) + `indicator_as_of` (`date <= as_of`). `compute_universe(session, universe, as_of)` composes `FactorEngine` + `ScoreEngine` over it.
- **Gap:** no test proves the **full score** (cross-sectional normalization + blend) is leakage-free, and none is framed as a **non-vacuous, non-skippable regression**.

## Locked decisions

- **Score-level counterfactual trap** (`tests/integration/test_scoring_leakage.py`): seed a small multi-stock universe with pre-`as_of` data; compute the **full scores** via `compute_universe(..., EARLY)` → **baseline**; then inject **post-`as_of` trap data** (future-dated indicators + a later-knowledge-time fundamental restatement, extreme values that *would* move scores if leaked); recompute `compute_universe(..., EARLY)` → **with-trap**; **assert every stock's composite + sub-scores + coverage are identical.** This proves scoring (not just a factor) uses no post-`as_of` data.
- **Non-vacuous by construction:** (a) the baseline is asserted **non-empty with real coverage > 0** (can't pass on empty data); (b) a **"trap has teeth"** test computes `compute_universe(..., LATE)` (after the trap is knowable) and asserts **at least one composite changes** — proving the trap is impactful, so the "unchanged at EARLY" result is meaningful.
- **Both leakage vectors** in one trap: future **indicators** (`date > as_of`) and a later-**knowledge** fundamentals restatement (`knowledge_time > as_of`).
- **Non-skippable in CI:** the test is `@pytest.mark.integration` and runs in the **required `backend-rls` gate** (`pytest -m integration`) which has a **mandatory Postgres service** — a DB outage **fails** that job (red), it does not silently skip to green. Combined with the non-vacuous assertions, the guard cannot pass falsely. (A pure no-DB unit test can't exercise the real PIT SQL reads, so integration is the correct — and, in the required gate, unconditional — home.)
- **No production code change** — a test-only story. Reuse the `test_factor_pit.py` seeding idioms (`admin_engine`, `record_fundamental_version`, raw `technical_indicators` inserts) + throwaway rows cleaned up.

## Acceptance Criteria

1. **Counterfactual guard.** A synthetic fixture computes scores as-of `EARLY`, injects post-`as_of` trap data, recomputes as-of `EARLY`, and **asserts scores are identical** (composite + 5 sub-scores + coverage, per stock). Fails if any post-`as_of` datum leaks.
2. **Non-vacuous.** Baseline scores are non-empty with `coverage > 0`; a **"trap has teeth"** test proves the trap moves scores when computed as-of `LATE` (so AC #1 can't pass because the trap was inert).
3. **Both vectors.** The trap includes a future-dated indicator **and** a later-knowledge fundamentals restatement; both are shown invisible at `EARLY`.
4. **Non-skippable.** Runs in the required `backend-rls` CI gate (real Postgres, `-m integration`); documented why that makes it unconditional. Cleaned-up throwaway data.
5. **Gates.** `ruff` + `ruff format` + `mypy --strict` + `lint-imports` + `pytest` (unit + the new integration test on real PG) green. No production code touched.

## Tasks / Subtasks

- [x] **Task 1 — fixture** (AC: #1, #3)
  - [x] `tests/integration/test_scoring_leakage.py`: seed a market + ≥3 stocks (a sector) with pre-`as_of` indicators (`ret_6m`,`beta_1y`, varied) + pre-`as_of` fundamentals (`pe`, knowledge < EARLY, varied). A `_inject_trap(...)` helper adds future indicators (`date` in (EARLY, LATE]) + a later-knowledge `pe` restatement (knowledge in (EARLY, LATE]) with extreme values. Cleanup fixture.
- [x] **Task 2 — counterfactual + teeth tests** (AC: #1, #2)
  - [x] `_scores_by_stock(compute_universe(...))` helper → `{stock_id: (composite, sub-scores, coverage)}`. `test_scores_unchanged_by_post_as_of_data` (baseline == with-trap at EARLY; baseline non-empty, coverage > 0). `test_trap_data_moves_scores_once_knowable` (EARLY vs LATE differ). Optionally assert the sub-score category the trap targets is the one that moves.
- [x] **Task 3 — gates + reconcile** (AC: #4, #5)
  - [x] Run `ruff`/`mypy`/`lint-imports`/`pytest` (+ the integration test on real PG). Confirm it's collected by `-m integration`. Reconcile QV-036 → done (already applied).

## Dev Notes

### The counterfactual
```
baseline  = scores( compute_universe(universe, EARLY) )        # only pre-as_of data exists
inject_trap()                                                   # future indicators + later-knowledge pe restatement
with_trap = scores( compute_universe(universe, EARLY) )        # same as_of, trap now in the DB but post-as_of
assert with_trap == baseline                                    # ⇒ no leakage (scoring ignored the trap)
assert scores(compute_universe(universe, LATE)) != baseline     # ⇒ trap has teeth (would be caught if leaked)
```
Cross-sectional normalization means a single leaked value would shift *percentiles across the universe* — so "all scores identical" is a strong assertion.

### Seeding idioms (mirror `test_factor_pit.py`)
- `record_fundamental_version(session, stock_id, _PERIOD, "quarterly", {"pe": Decimal(...)}, knowledge_time=...)`.
- `INSERT INTO technical_indicators (stock_id, date, ret_6m, beta_1y) VALUES ...`.
- Dates: `_PERIOD=2025-12-31`; pre-`as_of` indicator `2026-01-10`, pre-`as_of` knowledge `2026-01-05`; **`EARLY=2026-01-20`**; trap indicator `2026-02-15`, trap knowledge `2026-02-10`; **`LATE=2026-03-15`**.
- `compute_universe(session, universe, as_of)` returns `list[StockScore]` (`stock_id, fundamental/momentum/quality/sentiment/risk, composite, coverage, decomposition`).

### Boundaries
Test-only; no `src/` change. Integration (real PG) is required — the PIT boundary lives in the SQL reads (`ScoringContext`), so a no-DB unit test would prove nothing. `lint-imports` unaffected (tests aren't in the DAG). **Not this story:** backtest bias tests (`05` §4, later epic), a no-DB structural unit guard (possible future addition).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (BMAD dev-story workflow, executed inline)

### Debug Log References

- **New test passes on real Postgres:** `pytest tests/integration/test_scoring_leakage.py` → **2 passed**
  (counterfactual + trap-has-teeth). Collected by `-m integration` (confirmed) → runs in the required
  `backend-rls` gate.
- **Full backend gates green:** `ruff` + `ruff format --check` clean · `mypy --strict` Success (154 files) ·
  `lint-imports` 3/3 · full `pytest` suite passes (the 3 skips are the Docker/promtool/Kafka-gated ones,
  unrelated). **No `src/` changed.**

### Completion Notes List

- **Look-ahead bias in *scoring* now has a permanent, self-validating guard** — the credibility backstop for
  the decomposition/detail surfaces (QV-036) and everything downstream.
- **`test_scoring_leakage.py`** (integration, real PG): seeds a 3-stock universe (sector `IT`) with pre-`as_of`
  indicators (`ret_6m`/`beta_1y`) + a pre-`as_of` `pe` filing, computes the **full scores** via
  `compute_universe(EARLY)` as the **baseline**, injects **post-`as_of` trap data** (a future-dated indicator +
  a later-knowledge-time `pe` restatement, extreme values), recomputes `compute_universe(EARLY)`, and asserts
  **every stock's composite + 5 sub-scores + coverage are identical** → scoring used no future data. Because the
  score is a **cross-sectional** normalization, a single leaked value would shift percentiles across the whole
  universe — so "all identical" is a strong assertion.
- **Non-vacuous by construction:** baseline asserted non-empty with `coverage > 0`; a **"trap has teeth"** test
  (`compute_universe(LATE)` differs from baseline) proves the trap data is impactful — so the counterfactual
  can't pass because the trap was inert. The two tests **cross-validate** each other.
- **Both leakage vectors** covered: future indicator (`date > as_of`, blocked by `date <= as_of`) + later-
  knowledge restatement (`knowledge_time > as_of`, blocked by the bitemporal read).
- **"Non-skippable":** it's `@pytest.mark.integration`, run by the required `backend-rls` job (mandatory Postgres
  service) — a DB outage **fails** that job rather than skipping to green; combined with the non-vacuous
  assertions, the guard cannot pass falsely. A no-DB unit test can't exercise the real PIT SQL reads, so
  integration is the correct home. Deferred: a structural no-DB unit guard (asserting `ScoringContext` never
  passes an out-of-bound to its collaborators) — a possible future belt-and-braces addition.

### File List

**New (backend/)** — `tests/integration/test_scoring_leakage.py` (2 tests + fixture + trap helper).
**Modified (repo):** `_bmad-output/.../sprint-status.yaml` — QV-037 status; QV-036 → done (housekeeping).
**No production code changed.**

### Change Log

- **2026-07-08 — QV-037 leakage/PIT regression for scoring.** A score-level counterfactual guard (`05` §1.1):
  compute scores as-of `EARLY`, inject post-`as_of` trap data (future indicator + later-knowledge `pe`
  restatement), recompute — every score must be identical (no look-ahead). Non-vacuous via a "trap has teeth"
  companion (`LATE` moves scores) + a `coverage > 0` baseline check; both leakage vectors covered. Runs in the
  required `backend-rls` CI gate (real Postgres, `-m integration`) — effectively non-skippable. Test-only, no
  `src/` change; ruff/mypy-strict/import-linter + full suite green. Protects the credibility of the scores the
  QV-036 detail page displays.

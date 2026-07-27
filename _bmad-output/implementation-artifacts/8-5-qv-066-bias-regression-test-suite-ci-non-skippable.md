---
baseline_commit: 5a12fdf27d24fc628d382dc1a5ed333277120e14
---

# Story 8.5: QV-066 — Bias regression test suite (CI, non-skippable)

Status: review

**Epic:** EPIC-BT (Epic 8) · **Points:** 5 · **Depends:** QV-063 (`ranked_universe`/`price_panel` PIT reads), QV-064 (survivorship-free `universe_as_of`), QV-065 (`BacktestEngine` loop)

> **The permanent guards against the two cardinal sins.** QV-063/064/065 each proved a piece (data leakage, survivorship, loop mechanics). This story consolidates them into a **dedicated, clearly-named, CI-required** bias-regression suite that drives the **whole `BacktestEngine`** over synthetic data and **fails iff** the engine (a) leaks future data or (b) drops delisted names. These are counterfactual fixtures — engineered so a passing run is only possible when the engine is bias-free — wired into CI as a required, **non-skippable** check (`05` §4, `08` §5). It is a **test-only** story: no production code, no schema, no API.

## Story

As QA, I want permanent guards against the two cardinal sins, so credibility can't silently regress.

## Acceptance Criteria

1. **No-look-ahead guard (engine-level counterfactual)** — a real-Postgres test runs the full `BacktestEngine` over a synthetic universe and proves post-`as_of` data is invisible: parametrised over `(range_end ∈ {EARLY, LATE})` × `(trap ∈ {absent, present})` where the trap is future-dated indicators + a later-knowledge fundamentals restatement + a post-`EARLY` price spike, all extreme enough to reorder the ranking. **At `EARLY`: with-trap metrics == without-trap metrics** (the trap is in the future → invisible → no leak). **At `LATE`: with-trap metrics != without-trap metrics** (the trap is now knowable at a post-trap rebalance → rankings move → the guard is non-vacuous / "has teeth").
   [Source: `05` §4.1; QV-037/QV-063 counterfactual pattern lifted to the engine]

2. **No-survivorship guard (engine-level counterfactual)** — a synthetic universe where a **high-ranked** name is a member from the start and **delists mid-backtest** (`effective_to` + `delisted_on` set, price bars stop at the delist date). Running the engine through the real survivorship-free seam vs a **deliberately biased** seam (current-members-only, i.e. `active_universe` semantics) yields **different metrics** — proving the engine's result depends on including the later-delisted name. Also assert directly that `universe_as_of(D_before_delist)` **includes** the name while the biased read **excludes** it, and that the name is **force-exited at its last valid price** (not dropped/zeroed).
   [Source: `05` §4.2; QV-064 survivorship-free universe; QV-065 forced exit]

3. **Drives the real engine + real seam** — the tests run `BacktestEngine(seam)` where `seam` is a thin adapter over the **real** `BacktestDataAccess` (real `ranked_universe`/`price_panel`/`last_price_as_of` DB reads); only the engine's hard-coded `universe_as_of(index_code="NIFTY200", market="NSE")` is redirected to the synthetic seeded index/market. No mocking of the PIT logic — the guards exercise the actual look-ahead/survivorship code paths, so a regression **in the engine or the seam** trips them.
   [Source: QV-065 `BacktestData` Protocol; QV-063/064 seam]

4. **Wired into CI as a required, non-skippable check** — the suite carries a dedicated `bias` pytest marker (registered in `pyproject.toml`) **and** `integration`. A named CI step in the required `backend-rls` job runs `pytest -m bias` so the guards are a visible required check (matching `08` §5's pipeline: *"Backtest bias regression tests are mandatory and non-skippable"*). Because `backend-rls` provides a live Postgres, the integration auto-skip never fires there — the guards actually execute on every backend PR.
   [Source: `08` §5; `.github/workflows/ci.yml` `backend-rls` → `pytest -m integration`; `ci-success` required gate]

5. **Test-only, deterministic, self-cleaning** — no production/src changes, no schema, no migration, no API. Seeds on the `admin_engine` inside a rolled-back transaction (no residue), synthetic market/index codes (no collision with real NIFTY200/NSE data), deterministic (pure function of seeded PIT data). Full-tree gates green (ruff, ruff format, **bare `mypy`**, lint-imports **3/3**, bandit, pip-audit).
   [Source: QV-063/064 real-PG test conventions; testing rules]

---

## Dev Notes

### The one technique that makes this hermetic

`BacktestEngine.run` calls `self._data.universe_as_of(D, index_code=spec.universe)` where `spec.universe` is the `Literal["NIFTY200"]` — and `universe_as_of`'s `market` defaults to `"NSE"`. Real NIFTY200/NSE data exists in dev, so a synthetic-seed test can't use those codes directly. **Redirect via a thin adapter** that satisfies the QV-065 `BacktestData` Protocol:

```python
class _SyntheticSeam:  # routes the engine to a synthetic index; real seam for everything else
    def __init__(self, session, index_code, market):
        self._d = BacktestDataAccess(session)
        self._index, self._market = index_code, market
    def universe_as_of(self, as_of, *, index_code="NIFTY200", market="NSE"):
        return self._d.universe_as_of(as_of, index_code=self._index, market=self._market)
    def ranked_universe(self, *a, **k): return self._d.ranked_universe(*a, **k)
    def price_panel(self, *a, **k):     return self._d.price_panel(*a, **k)
    def last_price_as_of(self, *a, **k): return self._d.last_price_as_of(*a, **k)
```

Now `BacktestEngine(_SyntheticSeam(session, idx, mkt)).run(spec)` runs the **real** engine + **real** PIT reads over hermetic synthetic data. For the survivorship guard, a second `_BiasedSeam` overrides `universe_as_of` to return only **currently-active/open** members (mirroring `active_universe`) — the "wrong" engine, whose result must differ.

### Seeding recipe (reuse — do NOT invent)

- **Scores need factor data.** `ranked_universe(D, …)` runs `compute_universe` → the Factor/Score engines, which read `technical_indicators` (`ret_6m`, `beta_1y`, …) and bitemporal `fundamentals`. Seed as `tests/integration/test_backtest_data.py` (QV-063) does: `record_fundamental_version(session, sid, period_end, "quarterly", {"pe": …}, knowledge_time=…)` for fundamentals; a `technical_indicators` insert (`ret_6m`, `beta_1y`) dated **before `START`** so rankings are stable across rebalances; `daily_prices` (`close`+`adj_close`) across the session range.
- **Membership** via a direct `index_constituents` insert (`index_code, stock_id, effective_from, effective_to, weight`) under the **synthetic** index code; the delisted name gets `effective_to = DELIST` + `stocks.delisted_on = DELIST` and price bars only up to `DELIST`.
- **Dates:** pick `START`, `EARLY`, `TRAP_DATE` (`EARLY < TRAP_DATE < LATE`), `LATE` so monthly rebalances fall on both sides of `TRAP_DATE`. Use `sessions_in_range` to know the session dates you must price.
- Reuse the rolled-back-connection + `Session(bind=conn)` fixture shape from `test_historical_universe.py` (QV-064) so there's zero residue; synthetic `market.code` / `index_code` (e.g. `f"BT{uuid4().hex[:6]}"`) avoid colliding with real reference data.

### The two counterfactuals (mirror QV-037, at the engine level)

- **Leak guard:** the trap is *post-`EARLY`* data that would change the ranking **if** any rebalance `≤ EARLY` could see it. Correct engine ⇒ `EARLY` run identical with/without trap. Teeth ⇒ `LATE` run (a rebalance sees the trap) differs. Assert on the serialized `metrics` dict (e.g. `total_return`/`benchmark_return`), which is a pure function of the picks.
- **Survivorship guard:** the delisted name must rank **high** at the early rebalances (seed its `ret_6m` at the top) so it is actually *held*; then it delists. Survivorship-free engine ⇒ it participated + force-exited. Biased engine (`active_universe`) ⇒ never held ⇒ different metrics. The metric divergence is the guard; the direct `universe_as_of` vs biased-read assertion is the explanation.

### Scope boundary

- **Test-only.** If a guard fails because the engine is genuinely biased, that's a real bug to fix in QV-065 code — but this story does not modify engine code; it only adds the guards. (If wiring reveals a real engine bug, fix it and note it — "leave the system correct.")
- The **existing** primitive guards stay: `test_scoring_leakage.py` (QV-037), `test_backtest_data.py` (QV-063), `test_historical_universe.py` (QV-064). QV-066 adds the **engine-level** consolidation, not a replacement.
- Full metrics suite (QV-068), reproducibility formalisation (QV-069), UI (QV-071) are unrelated.

### Previous-story / epic intelligence

- **QV-065 (merged PR #74)** made the engine depend on the `BacktestData` **Protocol** — that's exactly what lets `_SyntheticSeam`/`_BiasedSeam` drive it. The engine reads `universe_as_of`/`ranked_universe`/`price_panel`/`last_price_as_of` only. `last_price_as_of` is called on every forced exit (spyable). Metrics are deterministic Decimal strings — safe to compare for equality.
- **QV-063/064** established the real-PG counterfactual + rolled-back-seed conventions and the `run bare mypy` gate; `scripts` is an importable package.
- The engine hard-codes `spec.universe`/market `"NSE"` — the redirect adapter is the sanctioned way around it for a hermetic test (no engine change needed).

### Git intelligence (recent)

`5a12fdf QV-065 #74` · `fc0ff2c QV-064 #73` · `3517e40 QV-063 #72`. `tests/integration/test_backtest_engine_run.py` (QV-065) is the closest template for seeding + the seam; `test_backtest_data.py` for the scoring seed (indicators + fundamentals); `test_historical_universe.py` for the rolled-back membership fixture.

### Project context reference

`_bmad-output/project-context.md` — PIT correctness is the cardinal rule of Epic 8; `backend/src/quantvista/<context>/`; money as `Decimal` via `str`. `08` §5: bias regression tests are mandatory + non-skippable.

## Tasks / Subtasks

### Task 1: Test seam adapters (AC-3)
- [x] `_SyntheticSeam` (redirects `universe_as_of` to the synthetic index/market, delegates the rest to a real `BacktestDataAccess`, spies `last_price_as_of`) and `_BiasedSeam` (current-members-only via the real `active_universe`). Both satisfy the `BacktestData` Protocol (mypy-verified).

### Task 2: Synthetic fixtures (AC-5)
- [x] Two rolled-back `admin_engine` fixtures (`leak`, `surv`): synthetic market + index + 3 stocks each with `technical_indicators` (`ret_6m`), bitemporal `fundamentals`, `daily_prices` across the session range; the survivorship one delists a top-ranked name mid-range (`effective_to`/`delisted_on` + truncated prices).

### Task 3: No-look-ahead guard (AC-1)
- [x] `test_no_lookahead_at_early` (run at EARLY, inject post-EARLY trap, re-run → **identical** metrics) + `test_trap_has_teeth_at_late` (same trap at LATE → **different** metrics). Trap = future-dated `ret_6m` spike + a post-EARLY price spike (upsert) + a later-knowledge `pe` restatement.

### Task 4: No-survivorship guard (AC-2)
- [x] `test_survivorship_free_differs_from_biased` (`_SyntheticSeam` vs `_BiasedSeam` → metrics differ); `test_universe_read_includes_delisted_but_biased_excludes`; `test_delisted_name_force_exited` (`last_price_as_of` spy).

### Task 5: CI wiring — required + non-skippable (AC-4)
- [x] Registered the `bias` marker in `pyproject.toml`; suite marked `integration` + `bias`. Added a named `pytest -m bias` step to the `backend-rls` job (part of the required `ci-success` gate).

### Task 6: Gates (AC-5)
- [x] Full-tree gates green (ruff, ruff format, bare `mypy` (268), lint-imports 3/3, bandit, pip-audit); `pytest -m bias` → 5 passed; full suite 729 passed / 5 skipped. Story Status → review; sprint-status → review; Dev Agent Record filled.

## Dev Agent Record

### Debug Log

- RED: the two look-ahead tests first failed on a `daily_prices` unique-violation — the trap's post-EARLY price spike collided with C's already-seeded session bar. Fixed by making the trap price an **upsert** (`ON CONFLICT (stock_id, date) DO UPDATE SET adj_close`).
- **Hermetic technique:** the engine hard-codes `universe_as_of(index_code="NIFTY200", market="NSE")`; `_SyntheticSeam` redirects only that call to the synthetic index while delegating `ranked_universe`/`price_panel`/`last_price_as_of` to the real `BacktestDataAccess` — so the actual PIT code runs. `_BiasedSeam` swaps in the existing `active_universe` reader (current-members-only) to model the survivorship-biased engine.
- **Non-vacuous by construction:** at EARLY the top pick (A, `ret_6m` 0.30) is chosen with or without the trap — but *if the engine leaked* the trap (C, `ret_6m` 0.99, dated after EARLY), C would outrank A and the metrics would differ. So a leak would flip `test_no_lookahead_at_early` red; the teeth test proves the trap does move the result once knowable (C picked in May/Jun).
- mypy tidy: stored the session on the seam (`self._sess`) instead of reaching into `BacktestDataAccess._session`; typed `seam_cls: type[_SyntheticSeam]`.
- Gate fixes: E501s in SQL/comment lines → split.

### Completion Notes List

- Two permanent, engine-level counterfactual guards that **fail iff** the backtest leaks future data or drops delisted names — the QV-037/063/064 pattern lifted to the whole `BacktestEngine` via a redirect seam over the real PIT reads.
- Wired as a **required, non-skippable** CI check: `bias` marker + a dedicated `pytest -m bias` step in `backend-rls` (live Postgres there → the integration auto-skip never fires, so the guards always execute on backend PRs). Matches `08` §5 ("mandatory + non-skippable").
- **Test-only** — no production/schema/API change. The engine passed both guards as-is (no bias bug surfaced), so no QV-065 code change was needed.
- Deterministic, rolled-back synthetic seed (synthetic market/index codes → no collision with real NIFTY200/NSE); `pytest -m bias` → 5 passed / 729 deselected; full suite 729 passed / 5 skipped; all gates green.

### File List

- `backend/tests/integration/test_bias_regression.py` (new — 5 bias guards + seams + fixtures)
- `backend/pyproject.toml` (modified — registered the `bias` pytest marker)
- `.github/workflows/ci.yml` (modified — `pytest -m bias` step in `backend-rls`)

### Change Log

- 2026-07-27 — QV-066 bias-regression suite: engine-level no-look-ahead + no-survivorship counterfactual guards driving the real `BacktestEngine` over synthetic data via `_SyntheticSeam`/`_BiasedSeam`; registered `bias` marker + required non-skippable `pytest -m bias` CI step. Test-only; 5 guards; gates green.

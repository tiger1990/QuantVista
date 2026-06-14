# Sprint 08 — Backtesting I (Engine & Bias Controls)

**Phase:** 4 · **Goal:** the async backtest engine with the two cardinal bias controls and CI-enforced bias
regression tests — the credibility feature.
**Exit gate:** a bias-controlled factor-strategy backtest runs async and returns metrics.

> See `../05-domain-and-quant.md` §4, `../04` §3.6, `../06` (run_backtest).

---

### QV-062 — Backtest spec + schema (async) `[BE]` · `5pts` · Epic: EPIC-BT · depends: QV-007
**Story:** As a user, I want to submit a backtest and poll for results, so long runs don't block me.
**Acceptance criteria:**
- `backtests` table (tenant-scoped, RLS) with `spec JSONB`, status, result_ref, metrics; `POST /backtests` →
  `202` queued; `GET /backtests/{id}` polls status.
**Notes:** `04` §3.6; `03` §4.3.

### QV-063 — PIT data access for backtests `[QUANT]` · `8pts` · Epic: EPIC-BT · depends: QV-021, QV-030
**Story:** As a quant, I want the engine to read only data knowable at each rebalance date, so there's no
look-ahead bias.
**Acceptance criteria:**
- At date `D`, scores/fundamentals/prices read via `as_of(D)` (knowledge_from ≤ D); engine structurally
  cannot see post-`D` data.
**Notes:** `05` §4.1; `03` §5.

### QV-064 — Survivorship-free historical universe `[QUANT]` · `5pts` · Epic: EPIC-BT · depends: QV-019, QV-013
**Story:** As a quant, I want the *historical* index membership including delisted names, so backtests aren't
survivorship-biased.
**Acceptance criteria:**
- Universe at `D` from `index_constituents` as-of `D`; delisted names handled as forced exit at last valid
  price.
**Notes:** `05` §4.2.

### QV-065 — Backtest engine core (rebalance loop + frictions) `[QUANT]` · `8pts` · Epic: EPIC-BT · depends: QV-063, QV-064, QV-053
**Story:** As a quant, I want a realistic rebalance simulation, so results reflect tradeable reality.
**Acceptance criteria:**
- Factor-strategy loop (rank_by, top_n, rebalance cadence) with transaction costs (bps), slippage, turnover;
  adjusted-return based; benchmark = Nifty 200 TRI; deterministic (seeded).
- Runs on the `user` queue with per-tenant concurrency cap; progress streamed to `backtests`.
**Notes:** `05` §4; `06` §4.

### QV-066 — Bias regression test suite (CI, non-skippable) `[QUANT]` · `5pts` · Epic: EPIC-BT · depends: QV-063, QV-064
**Story:** As QA, I want permanent guards against the two cardinal sins, so credibility can't silently regress.
**Acceptance criteria:**
- Synthetic fixtures that fail iff the engine leaks future data or drops delisted names; wired into CI as
  required checks.
**Notes:** `05` §4; `08` §5.

**Sprint total:** ~36 pts · **Milestone:** bias-controlled backtests proven by tests.

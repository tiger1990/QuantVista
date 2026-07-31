---
baseline_commit: 9c6f07b2c2a60234f861b944f7c8a482d3851584
---

# Story 10.3: QV-070 — Methodology & Disclaimer page

Status: ready-for-dev

**Epic:** EPIC-COMP (Epic 10) · **Points:** 3 · **Depends:** QV-011 (compliance content draft — **still `backlog`, see the blocker below**)

> **The trust surface.** A single published page that says *how the numbers are made* — scoring methodology and weights, point-in-time and survivorship controls, backtest cost assumptions — and states the **non-advice posture** plainly. QV-071 removed a `/methodology` link from the backtest tearsheet because the route 404'd and rendered as an empty page; this story builds the page and restores the link. Everything the page states is already true of the code and is cited below, so the *factual* content needs no invention. The **legal/marketing wording** is a product-compliance deliverable (QV-011 → finalised in QV-086), not an engineering one.

## Story

As compliance/product, I want published methodology + assumptions, so the research-tool posture is explicit and trust is built.

## ⚠️ Dependency status — read before starting

**QV-011 ("Compliance content draft: methodology + non-advice disclaimer") is `backlog`.** QV-070 depends on it. Two consequences the dev agent must respect:

1. **Do not invent legal wording.** Write the *factual* methodology sections (they are derived from code and `05`/`07`, cited below). For the disclaimer, **reuse the constants that already exist** rather than authoring new legal text — see AC-6. Final copy is launch-gated by QV-086.
2. **QV-011's second AC is already implemented.** `DISCLAIMER = "Research signal, not investment advice."` and the `X-QuantVista-Disclaimer: research-only; not investment advice` header live in `backend/src/quantvista/api/routes_stocks.py:26-28` and are already applied across stocks/screener responses, plus `alerts/email_render.py:31`. Reuse them; do not create a second source of truth. Flag to the user that QV-011 is effectively part-done so its status can be corrected.

If the user wants approved copy first, this story should be paused in favour of QV-011.

## Acceptance Criteria

1. **A public `/methodology` route** — `frontend/src/app/methodology/page.tsx`, **outside** the `(app)` group. `(app)/layout.tsx` redirects anonymous users to `/login`, so a page placed there would be invisible to prospects and to anyone reading a shared link; the methodology page is a trust surface and `07` §1.3 makes it launch-blocking, so it must render without auth. It uses the root layout; give it a minimal header and a "Back to app" affordance rather than `AppNav` (which assumes an authed session).
   [Source: `src/app/(app)/layout.tsx` auth guard; `plans/07-security-and-compliance.md` §1.3]

2. **Scoring methodology section — accurate to `score-v1`.** Document the real pipeline: per factor, direction-adjust the raw value (× direction so higher = better) → **winsorize to the sector's [p1, p99]** → **sector z-score** (sample std; σ=0 or singleton → neutral 0) → rank to `percentile_sector` (0–100) and `percentile_universe`. Categories are blended with the **published weights**: fundamental **0.40**, momentum **0.20**, quality **0.20**, sentiment **0.10**, risk **0.10** (`weights_version` `v1`). State that `model_version` is `score-v1` and that **any methodology change bumps it**. Mention `coverage` (a name with zero factor coverage gets **no** score rather than an imputed one). Values must be read from the code, not retyped by hand where avoidable.
   [Source: `analytics/normalizer.py` docstring + `_WINSOR_LO/_HI`; `analytics/scoring.py` `MODEL_VERSION`, `DEFAULT_WEIGHTS`, `coverage`; `plans/05-domain-and-quant.md` §1.2]

3. **Point-in-time & survivorship section.** Explain the two controls in plain language and say they are *structurally* enforced, not merely intended: reads go through a PIT seam bounded by `as_of` (QV-063), index membership is **survivorship-free** — a name delisted later is still a member on the dates it was one (QV-064) — and a **permanent, non-skippable CI suite** (QV-066) fails the build on look-ahead or survivorship regressions. This is the strongest trust claim the product has; state it precisely and do not overstate it.
   [Source: `analytics/backtest_data.py` (`universe_as_of`, `returns_as_of`); `tests/integration/test_bias_regression.py`; QV-066 story]

4. **Backtest assumptions section — including the honest caveats.** Document: equal-weight allocation across selections; rebalance cadence (weekly/monthly/quarterly); returns on **adjusted close**; costs = the user's `costs_bps` **plus a fixed `SLIPPAGE_BPS = 5`** applied to each unit of turnover; delisted holdings force-exit at last available price. **Two caveats must be stated plainly, not buried:**
   - **The benchmark is an internal proxy, not the licensed Nifty 200 TRI** — it is an equal-weight buy-and-hold of the PIT universe at the start date. Real TRI licensing is deferred (see the market-data provider strategy). A user comparing to a published index number will otherwise be misled.
   - **Backtest results depend on ingested data coverage**; a range outside the ingested history returns a degenerate, all-zero result rather than an error.
   [Source: `analytics/backtest.py` `SLIPPAGE_BPS`, `WEIGHTS_VERSION`, `_equal_weight`, benchmark construction in `run()`; QV-065 story §5]

5. **Reproducibility section.** Explain `reproducibility_hash` = SHA-256 of the canonical spec + `model_version` + `weights_version`: two runs sharing it used an identical **recipe**. State explicitly that it **does not fingerprint the underlying market data**, which can change between runs. It is returned by the API and persisted in `metrics`; QV-071 deliberately removed it from the tearsheet UI as an audit artifact, so this page is where it gets explained.
   [Source: `analytics/backtest.py` `_reproducibility_hash`; QV-069 story; QV-071 Debug Log]

6. **Non-advice posture — reusing existing constants.** Render the `07` §1 rules in user-facing language: no personalisation/suitability; research-signal terminology (never "we recommend you buy"); no execution, custody, or brokerage; disclaimers wherever research output appears. The page's disclaimer text must come from **one shared source** with the existing API constant, not a fresh string literal — either import/mirror `DISCLAIMER` into a single frontend constant or expose it via the API. A test must pin that the page and the API disclaimer cannot drift apart.
   [Source: `plans/07-security-and-compliance.md` §1; `api/routes_stocks.py:26-28`; `alerts/email_render.py:31`]

7. **Link it back — restore what QV-071 removed, and add the score surfaces.** Re-add the "Methodology" link in `features/backtests/BacktestResults.tsx` (the QV-071 test `"links nowhere until the Methodology page exists (QV-070)"` **must be inverted, not deleted** — it exists precisely to be flipped by this story). Per AC in the sprint file the link must also appear on **score surfaces** (stock detail / rankings / screener) wherever a research figure is shown. Confirm each surface actually renders it.
   [Source: sprint-09 QV-070 AC "linked from backtest/score surfaces"; `features/backtests/BacktestResults.test.tsx`]

8. **Tests + gates.** Colocated vitest/RTL for the page: every required section renders; the disclaimer matches the shared constant; the benchmark-proxy and data-coverage caveats are present (they are the ones most likely to be quietly dropped); the page renders **without an authenticated session**. Frontend gates green: `npm run typecheck`, `npm run lint`, `vitest run`, `next build` (the route must appear in the build output and stay statically prerenderable). Backend untouched — if that changes, its gates must be green too.

## Tasks / Subtasks

- [ ] **Task 1 — Confirm the QV-011 posture with the user (AC: blocker)**
  - [ ] Report that QV-011 is `backlog` but its API-constant AC is already shipped; ask whether to proceed with factual content + existing constants, or pause for approved copy.
- [ ] **Task 2 — Public route + shell (AC: 1)**
  - [ ] `src/app/methodology/page.tsx` outside `(app)`; minimal header + back link; verify it renders logged-out.
- [ ] **Task 3 — Factual content sections (AC: 2, 3, 4, 5)**
  - [ ] Scoring pipeline + weights table; PIT/survivorship; backtest assumptions **with both caveats**; reproducibility.
  - [ ] Source every number from code; do not hand-copy a weight that could drift.
- [ ] **Task 4 — Non-advice posture from shared constants (AC: 6)**
  - [ ] Single source for the disclaimer string + a drift test.
- [ ] **Task 5 — Restore and extend links (AC: 7)**
  - [ ] Invert the QV-071 "links nowhere" test; add the link to score surfaces; verify each renders.
- [ ] **Task 6 — Tests + gates (AC: 8)**
  - [ ] Colocated tests incl. the caveat assertions and the logged-out render; run all four frontend gates.

## Dev Notes

### Placement & conventions

- **Public page, not `(app)`.** `src/app/(app)/layout.tsx` is a client component that `router.replace("/login")` for `status === "anon"`. Anything under `(app)` is unreachable logged-out. Put the page at `src/app/methodology/page.tsx` so it inherits only the root layout.
- **Prefer a server component.** The page is static prose; it needs no `"use client"`, no TanStack Query, and no auth. Keeping it server-rendered preserves the static prerender in `next build` (`○ /methodology`).
- **Design direction:** this is prose, not a dense analyst surface. Follow the editorial direction of the tearsheet for typography and hairlines, but a readable measure (`max-w-prose`-ish) beats the dense tabular treatment. See [[design-direction-editorial-analyst]].
- **Prettier note:** the repo has **no** prettier config and no format script; existing files are 100-column. If formatting, use `--print-width 100`, and never reformat files you did not change (a default-width run reflows unrelated code and pollutes the diff).

### The numbers this page must state (verified against code at baseline)

| Thing | Value | Source |
|---|---|---|
| `model_version` | `score-v1` | `analytics/scoring.py:31` |
| Category weights | fundamental .40 · momentum .20 · quality .20 · sentiment .10 · risk .10 | `analytics/scoring.py` `DEFAULT_WEIGHTS` |
| `weights_version` (scoring) | `v1` | same |
| Winsorisation | sector [p1, p99] before z | `analytics/normalizer.py` `_WINSOR_LO/_HI` |
| Normalisation | direction-adjust → winsorize → sector z → percentile (sector + universe) | `analytics/normalizer.py` docstring |
| Backtest slippage | fixed **5 bps** on traded turnover, added to `costs_bps` | `analytics/backtest.py` `SLIPPAGE_BPS` |
| Backtest weighting | equal-weight; `weights_version` `equal-weight-v1` | `analytics/backtest.py` `WEIGHTS_VERSION` |
| Benchmark | equal-weight buy-and-hold of the PIT universe at `start` — **proxy, not licensed TRI** | `analytics/backtest.py` `run()` |
| Costs range accepted | `costs_bps` 0–500 | `schemas/backtest.py` |

### Honesty requirements (do not soften these)

The value of this page is that it is *true*. Three statements are easy to quietly omit and must not be:

1. The benchmark is **not** the Nifty 200 TRI (licensing deferred) — it is an internal equal-weight proxy.
2. `reproducibility_hash` fingerprints the **recipe, not the data**.
3. Backtests over ranges outside ingested coverage return **zeroed** results, not errors.

### Previous-story intelligence (QV-071, merged PR #79)

- QV-071 **removed** the `/methodology` link because it 404'd into Next's bare default 404, which reads as a broken app. Its test `links nowhere until the Methodology page exists (QV-070)` is a deliberate tripwire for this story — invert it.
- QV-071 also removed `reproducibility_hash` from the tearsheet (deviation from its AC-5, at the user's request) — this page is now the only place it is explained.
- Epic 8 shipped five bugs found only in manual QA (queue routing, commit-before-response, curve anchoring, empty defaults, dead link). **Lesson for this story: actually load `/methodology` in a browser logged-out before calling it done** — a passing unit test did not catch the 404 that started this story.
- App-wide `CommitBeforeResponseRoute` now guards write routes; irrelevant here unless the page gains an API, but do not remove it.

### Git intelligence (recent)

`9c6f07b QV-071 #79` (this baseline) · `0c99b69 QV-069 #78` · `00e08e0 QV-068 #77`. Frontend page precedent: `src/app/(app)/*/page.tsx`; test precedent: `src/features/**/*.test.tsx`.

### Project context reference

`_bmad-output/project-context.md` · `plans/05-domain-and-quant.md` §1.2 (scoring) · `plans/07-security-and-compliance.md` §1 (posture) · frontend-architecture memory (Next.js client of the FastAPI system-of-record).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

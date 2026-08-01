# Non-advice terminology guide

> **Enforced, not aspirational.** The rules below live as data in
> `backend/src/quantvista/core/terminology.py` and are checked by
> `backend/tests/test_terminology_guard.py`, which scans every user-facing string in both trees and
> **fails the build** on a breach. This document is the human half; the test is the half that
> survives a rushed copy edit.

## Why this exists

QuantVista is a research tool, not an investment adviser. That posture (`plans/07-security-and-compliance.md` §1)
is not only about what the product *does* — it is about how the product *describes* what it does.
Regulated advice is characterised by personalisation and by inviting reliance. A screen that says
"top-ranked by composite score" is research; the same screen captioned "the best stocks to buy now"
is something else entirely, and no amount of disclaimer at the bottom of the page undoes it.

The failure mode is gradual. Nobody sets out to write advice; someone rewrites a heading to read
better, "screened candidates" becomes "our top picks", and the line has moved. Hence the test.

## Say this

| Use | Because |
|---|---|
| **research signal** | what a score is: an observation, not an instruction |
| **factor score** | a measured, reproducible quantity |
| **screened candidates** | the output of a filter *the user chose* |
| **simulated result** | what a backtest produces — never "returns you would have made" |

Two habits carry most of the weight:

1. **Describe, don't direct.** State what the data shows ("ranks in the top decile on momentum"),
   not what the reader should do about it.
2. **Never address the user's situation.** The platform holds no financial profile, so any sentence
   implying it knows the reader's circumstances is both wrong and a regulatory problem.

## Not this

Each phrase below fails the build. The replacement column is the point — the guard exists to
redirect, not merely to block.

| Banned | Why | Say instead |
|---|---|---|
| **we recommend** | states a house view and invites reliance — the core of regulated advice | describe what the signal shows: "ranks in the top decile on momentum" |
| **you should buy / sell / invest / hold** | a direct instruction to act, personalised by "you" | "screened candidates" — let the user decide what to do with them |
| **suitable for you** | suitability is the legal line between research and advice (`07` §1.1) | say nothing about suitability; the platform holds no user financial profile |
| **guaranteed returns / profits** | no equity outcome is guaranteed; misrepresentation, not just tone | "simulated result" or "historical performance", with the past-performance caveat |
| **assured returns** | same misrepresentation as "guaranteed", and specifically flagged in Indian markets | "simulated result" with its cost and coverage assumptions stated |
| **risk-free returns** | implies an outcome with no downside, which no screened equity carries | quote the risk metrics: volatility, max drawdown, beta |
| **sure shot** | tipster register; asserts certainty the data cannot support | "high-scoring on the composite" — a measurable claim |
| **multibagger** | promises a return multiple; common in Indian tip sheets and squarely advice-flavoured | report the factor scores and let the numbers speak |
| **will outperform / beat the market / rise** | a forecast stated as fact; scores are cross-sectional rankings, not predictions | "ranked higher than peers on this factor as of \<date\>" |
| **best stock(s) to buy** | an instruction dressed as a superlative | "top-ranked by composite score" |
| **our advice / our recommendation** | claims an advisory relationship the product does not have | "this research tool shows…" |

### Why these are phrases, not words

Banning "advice" or "recommend" outright would flag the disclaimer itself — *"Research signal, not
investment advice."* — and a guard that cries wolf is a guard people learn to skip. Every rule is
therefore phrase-level and targets the *construction* that turns an observation into an instruction.

## When you legitimately need banned wording

A few files exist to *discuss* this language — the methodology page quotes "we recommend you buy" to
explain what the product never says. Those are listed in `ALLOWED_CONTEXTS` in the terminology
module, each with a reason.

Treat an allowlist entry as a last resort: it is copy the guard stops checking entirely. A test caps
the list's size deliberately. **Prefer rewording over exempting.**

## What this guard does *not* do

- It cannot tell whether a *feature* constitutes advice. It checks language only.
- It does not review final launch copy — that is **QV-086**, and it is a human, compliance-owned
  decision.
- It does not scan test files (they assert *about* copy) or generated output.

## Related

- `plans/07-security-and-compliance.md` §1 — the regulatory posture these rules serve
- `/methodology` (QV-070) — the public page stating the posture, plus the scoring and backtest
  methodology
- `backend/src/quantvista/api/routes_stocks.py` — the `DISCLAIMER` constant and
  `X-QuantVista-Disclaimer` header carried on every research response
- `frontend/src/lib/disclaimer.ts` — the single frontend source of that same line

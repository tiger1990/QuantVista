---
baseline_commit: 492c77e058555706b4f3ce7e09ba657e0aec6de3
---

# Story 10.2: QV-011 — Compliance content draft: methodology + non-advice disclaimer

Status: review

**Epic:** EPIC-COMP (Epic 10) · **Points:** 3 · **Depends:** —

> **Closing the last engineering-owned piece.** Two of this story's three deliverables were already live before it was picked up: the `disclaimer` field + `X-QuantVista-Disclaimer` header constants shipped long ago, and QV-070 published the Methodology & Disclaimer page. What remained was the **non-advice terminology guide** `07` §1.2 calls for — and it is delivered here as an *enforced* artifact rather than a document that quietly decays.

## Story

As product/compliance, I want the disclaimer + methodology copy drafted, so research-tool posture is consistent across the UI/API.

## Acceptance Criteria (original) — disposition

| AC | State |
|---|---|
| Draft "Methodology & Disclaimer" page | **Delivered by QV-070** (PR #80) — public `/methodology`, statically prerendered |
| Non-advice terminology guide (`07` §1.2) | **Delivered here** — `docs/terminology-guide.md`, enforced by a build-failing test |
| `disclaimer` field + `X-QuantVista-Disclaimer` header constants (`04` §1) | **Already shipped** — `api/routes_stocks.py`, mirrored in `frontend/src/lib/disclaimer.ts` and drift-tested since QV-070 |

## What was built

1. **`core/terminology.py`** — the rules as data: 11 `BannedPhrase` entries, each carrying the regex, a human label, **why** it crosses the line, and **what to say instead**; 4 `PREFERRED_TERMS`; and a deliberately tiny `ALLOWED_CONTEXTS` list.
2. **`docs/terminology-guide.md`** — the human half: why the posture matters, the say-this/not-this tables, and an explicit account of what the guard does *not* do.
3. **`tests/test_terminology_guard.py`** — scans every user-facing string in **both** trees (`frontend/src/**/*.{ts,tsx}`, `backend/src/**/*.{py,j2,html}`) and fails the build on a breach, naming file, line, phrase, reason and replacement.

## Dev Agent Record

### Agent Model Used

claude-opus-5

### Debug Log

- **Rules were calibrated against the codebase before being written, not after.** A candidate sweep found exactly two hits, both in `methodology/page.tsx` — which quotes "we recommend you buy" to explain what the product never says, and states that no output judges what is "suitable for you". Both legitimate, which is what drove the `ALLOWED_CONTEXTS` design rather than discovering it as a failure later.
- **Phrase-level, not word-level, and that is the whole design.** Banning `advice` or `recommend` outright would flag the disclaimer itself — *"Research signal, not investment advice."* A guard that cries wolf gets skipped, so every rule targets the *construction* that turns an observation into an instruction.
- **Negative-controlled.** Planting `"we recommend you buy the best stocks to buy now"` into `BacktestList.tsx` failed the guard with two precise breaches (file:line, phrase, why, replacement). Restored immediately; `git diff` confirmed clean.
- **The guard guards itself.** `test_the_guard_actually_scans_something` fails if the file sweep ever silently matches nothing (>100 files expected) — otherwise every other assertion would pass vacuously. `test_every_allowance_is_justified_and_real` fails on a stale allowlist path, and `test_allowlist_stays_small` caps the exemptions, because the allowlist is the guard's weak point.
- **Doc/rules drift is also tested**: every banned label and preferred term must appear in `docs/terminology-guide.md`, so a rule cannot exist that nobody can read.

### Completion Notes List

- **Scope honesty:** this is a *language* guard. It cannot judge whether a **feature** constitutes advice, and it does not approve launch copy — that stays **QV-086**, human and compliance-owned. Both limits are stated in the guide itself rather than left implied.
- **India-specific phrasing included** (`multibagger`, `assured returns`, `sure shot`), because the tipster register is the realistic failure mode for this market, not generic US-style wording.
- **Test files are excluded from the scan** — they assert *about* copy, so scanning them would flag the very tests that verify banned phrasing is absent.
- **No frontend changes were needed:** the disclaimer was already collapsed to a single enforced source in QV-070, and the existing copy passes the guard clean.

### File List

- `backend/src/quantvista/core/terminology.py` (new — rules as data)
- `backend/tests/test_terminology_guard.py` (new — the enforcement)
- `docs/terminology-guide.md` (new — the human guide)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — QV-070 + QV-104 → done, QV-011 → in-progress)

### Change Log

- 2026-08-01 — QV-011: non-advice terminology guide delivered as enforced rules (11 banned phrasings with reasons and replacements, 4 preferred terms), scanning all user-facing strings in both trees. Gates: backend 811 passed/5 skipped, ruff/mypy/lint-imports clean; frontend 137 tests unaffected.

"""Non-advice terminology rules (QV-011) — the machine-readable half of the terminology guide.

`plans/07-security-and-compliance.md` §1.2 requires language discipline: research output is
described as a *signal*, never as a recommendation to act. A written guide alone erodes — one copy
edit reads better and the posture is gone, silently, because nothing checks. So the rules live here
as data and `tests/test_terminology_guard.py` fails the build on any string that breaks them.

This governs **how outputs are described**, not what the product does. It is a language guard, not a
substitute for compliance review: final launch copy is QV-086's job.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BannedPhrase:
    """A phrasing that turns a research signal into advice, plus why and what to say instead."""

    pattern: str  # regex, matched case-insensitively
    label: str  # how it reads in the guide and in failure output
    why: str
    instead: str


#: Phrases that make the product sound like an adviser. Deliberately phrase-level, not word-level:
#: banning "recommend" or "advice" outright would flag the disclaimer itself ("not investment
#: advice") and produce noise that trains people to ignore the guard.
BANNED_PHRASES: tuple[BannedPhrase, ...] = (
    BannedPhrase(
        pattern=r"\bwe recommend\b",
        label="we recommend",
        why="states a house view and invites reliance — the core of regulated advice",
        instead="describe what the signal shows: 'ranks in the top decile on momentum'",
    ),
    BannedPhrase(
        pattern=r"\byou should (?:buy|sell|invest|hold)\b",
        label="you should buy / sell / invest / hold",
        why="a direct instruction to act, personalised by the word 'you'",
        instead="'screened candidates' — let the user decide what to do with them",
    ),
    BannedPhrase(
        pattern=r"\bsuitable for you\b",
        label="suitable for you",
        why="suitability is the legal line between research and advice (07 §1.1)",
        instead="say nothing about suitability; the platform holds no user financial profile",
    ),
    BannedPhrase(
        pattern=r"\bguaranteed (?:returns?|profits?|gains?)\b",
        label="guaranteed returns / profits",
        why="no equity outcome is guaranteed; this is misrepresentation, not just tone",
        instead="'simulated result' or 'historical performance', with the past-performance caveat",
    ),
    BannedPhrase(
        pattern=r"\bassured returns?\b",
        label="assured returns",
        why="same misrepresentation as 'guaranteed', and specifically flagged in Indian markets",
        instead="'simulated result' with its cost and coverage assumptions stated",
    ),
    BannedPhrase(
        pattern=r"\brisk[- ]?free returns?\b",
        label="risk-free returns",
        why="implies an outcome with no downside, which no screened equity carries",
        instead="quote the risk metrics: volatility, max drawdown, beta",
    ),
    BannedPhrase(
        pattern=r"\bsure[- ]shot\b",
        label="sure shot",
        why="tipster register; asserts certainty the data cannot support",
        instead="'high-scoring on the composite' — a measurable claim",
    ),
    BannedPhrase(
        pattern=r"\bmultibagger\b",
        label="multibagger",
        why="promises a return multiple; common in Indian tip sheets and squarely advice-flavoured",
        instead="report the factor scores and let the numbers speak",
    ),
    BannedPhrase(
        pattern=r"\bwill (?:outperform|beat the market|rise|go up)\b",
        label="will outperform / beat the market / rise",
        why="a forecast stated as fact; scores are cross-sectional rankings, not predictions",
        instead="'ranked higher than peers on this factor as of <date>'",
    ),
    BannedPhrase(
        pattern=r"\bbest stocks? to buy\b",
        label="best stock(s) to buy",
        why="an instruction dressed as a superlative",
        instead="'top-ranked by composite score'",
    ),
    BannedPhrase(
        pattern=r"\bour (?:advice|recommendation)\b",
        label="our advice / our recommendation",
        why="claims an advisory relationship the product explicitly does not have",
        instead="'this research tool shows…'",
    ),
)

#: The vocabulary to use instead — the positive half of §1.2, quoted on the methodology page.
PREFERRED_TERMS: tuple[tuple[str, str], ...] = (
    ("research signal", "what a score is: an observation, not an instruction"),
    ("factor score", "a measured, reproducible quantity"),
    ("screened candidates", "the output of a filter the user chose"),
    ("simulated result", "what a backtest produces — never 'returns you would have made'"),
)

#: Files whose *purpose* is to discuss this language, so they legitimately contain it.
#: Kept deliberately tiny: every entry is a hole in the guard, so each needs a stated reason.
ALLOWED_CONTEXTS: tuple[tuple[str, str], ...] = (
    (
        "frontend/src/app/methodology/page.tsx",
        "the compliance page itself quotes banned phrasing to explain what the product never says",
    ),
    (
        "backend/src/quantvista/core/terminology.py",
        "this module — it defines the patterns",
    ),
    (
        "docs/terminology-guide.md",
        "the written guide — it lists every banned phrase by design",
    ),
)


def is_allowed_context(path: str) -> bool:
    """True if ``path`` is one of the few files that may contain banned phrasing."""
    normalised = path.replace("\\", "/")
    return any(normalised.endswith(allowed) for allowed, _ in ALLOWED_CONTEXTS)


__all__ = [
    "ALLOWED_CONTEXTS",
    "BANNED_PHRASES",
    "PREFERRED_TERMS",
    "BannedPhrase",
    "is_allowed_context",
]

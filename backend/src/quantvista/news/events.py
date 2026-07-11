"""Event-impact scoring (QV-045) — pure, deterministic, versioned.

A rule/keyword event classifier maps a headline to a material **event type** (contract win, earnings
beat/miss, up/downgrade, regulatory action, fraud, M&A, capital action, distress, management change,
or NONE); a versioned, configurable table gives each type a signed base **impact** (plan §1.4: +25
contract win, −40 ban). ``EventImpactScorer`` combines that base with the QV-044 sentiment into a
bounded ``impact_score``. Dev-grade + transparent — a learned event model is a later increment, as
FinBERT is for tone ([[sentiment-service-architecture]]). All numerics are ``Decimal`` (money rule).
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum

from quantvista.news.models import SentimentResult

IMPACT_RULESET_VERSION = "impact-v1"

# How strongly per-article tone moves the impact around the event base; NONE-event articles get a
# pure ``sentiment.score · GAIN`` contribution. Impact is clamped to a score-scale band.
SENTIMENT_GAIN = Decimal(25)
IMPACT_MIN, IMPACT_MAX = Decimal(-100), Decimal(100)


class EventType(StrEnum):
    CONTRACT_WIN = "contract_win"
    EARNINGS_BEAT = "earnings_beat"
    EARNINGS_MISS = "earnings_miss"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    MERGER_ACQUISITION = "merger_acquisition"
    CAPITAL_ACTION = "capital_action"
    MANAGEMENT_CHANGE = "management_change"
    REGULATORY = "regulatory"
    FRAUD_LITIGATION = "fraud_litigation"
    DISTRESS = "distress"
    NONE = "none"


# Versioned, configurable base impacts (signed, plan §1.4 scale). Editing this map / the patterns
# below is what "configurable" means; bump IMPACT_RULESET_VERSION when the semantics change.
IMPACT_WEIGHTS: dict[EventType, Decimal] = {
    EventType.EARNINGS_BEAT: Decimal(30),
    EventType.CONTRACT_WIN: Decimal(25),
    EventType.MERGER_ACQUISITION: Decimal(20),
    EventType.UPGRADE: Decimal(20),
    EventType.CAPITAL_ACTION: Decimal(15),
    EventType.MANAGEMENT_CHANGE: Decimal(-10),
    EventType.DOWNGRADE: Decimal(-25),
    EventType.EARNINGS_MISS: Decimal(-30),
    EventType.REGULATORY: Decimal(-40),
    EventType.FRAUD_LITIGATION: Decimal(-45),
    EventType.DISTRESS: Decimal(-50),
    EventType.NONE: Decimal(0),
}

# Whole-word / phrase cues per event type (case-folded). Kept deliberately specific — bare generic
# words ("order", "profit") are avoided so tone alone doesn't trip an event.
_PATTERNS: dict[EventType, tuple[str, ...]] = {
    EventType.CONTRACT_WIN: (
        "bags",
        "wins order",
        "wins contract",
        "bags order",
        "bags contract",
        "secures order",
        "wins deal",
        "awarded contract",
        "order win",
        "wins the order",
    ),
    EventType.EARNINGS_BEAT: (
        "beats",
        "beats estimates",
        "beats expectations",
        "profit jumps",
        "profit surges",
        "profit rises",
        "record profit",
        "tops estimates",
    ),
    EventType.EARNINGS_MISS: (
        "misses",
        "misses estimates",
        "profit falls",
        "profit drops",
        "loss widens",
        "profit declines",
        "posts loss",
        "slips into loss",
    ),
    EventType.UPGRADE: ("upgrade", "upgrades", "upgraded", "raised to buy", "rating upgrade"),
    EventType.DOWNGRADE: ("downgrade", "downgrades", "downgraded", "cut to sell", "rating cut"),
    EventType.MERGER_ACQUISITION: (
        "acquires",
        "acquisition",
        "merger",
        "to acquire",
        "buys stake",
        "takeover",
        "to merge",
    ),
    EventType.CAPITAL_ACTION: (
        "buyback",
        "share buyback",
        "dividend",
        "bonus issue",
        "stock split",
        "special dividend",
    ),
    EventType.MANAGEMENT_CHANGE: (
        "resigns",
        "steps down",
        "quits",
        "resignation",
        "sacked",
        "ousted",
    ),
    EventType.REGULATORY: (
        "ban",
        "bans",
        "banned",
        "probe",
        "sebi",
        "penalty",
        "raid",
        "show cause",
        "sanction",
    ),
    EventType.FRAUD_LITIGATION: (
        "fraud",
        "lawsuit",
        "scam",
        "misappropriation",
        "embezzlement",
        "sued",
        "indicted",
    ),
    EventType.DISTRESS: (
        "default",
        "defaults",
        "insolvency",
        "bankruptcy",
        "nclt",
        "liquidation",
        "wind up",
    ),
}


def _compile(patterns: tuple[str, ...]) -> re.Pattern[str]:
    alternation = "|".join(re.escape(p) for p in patterns)
    return re.compile(rf"\b(?:{alternation})\b")


_MATCHERS: dict[EventType, re.Pattern[str]] = {et: _compile(p) for et, p in _PATTERNS.items()}


def classify_event(text: str) -> EventType:
    """The dominant event in ``text`` (highest |impact| among matches); ``NONE`` if none match."""
    folded = (text or "").casefold()
    matched = [et for et, matcher in _MATCHERS.items() if matcher.search(folded)]
    if not matched:
        return EventType.NONE
    return max(matched, key=lambda et: abs(IMPACT_WEIGHTS[et]))


class EventImpactScorer:
    """Combine a headline's event type with its sentiment into a bounded ``impact_score`` (v1)."""

    ruleset_version = IMPACT_RULESET_VERSION

    def score(self, text: str, sentiment: SentimentResult) -> Decimal:
        base = IMPACT_WEIGHTS[classify_event(text)]
        raw = base + sentiment.score * SENTIMENT_GAIN
        return max(IMPACT_MIN, min(IMPACT_MAX, raw))

"""Unit tests for the event classifier + EventImpactScorer (QV-045) — pure, deterministic."""

from __future__ import annotations

from decimal import Decimal

from quantvista.news.events import (
    IMPACT_RULESET_VERSION,
    EventImpactScorer,
    EventType,
    classify_event,
)
from quantvista.news.models import SentimentResult

_NEUTRAL = SentimentResult(label="neutral", score=Decimal(0), confidence=Decimal(0))
_POS = SentimentResult(label="positive", score=Decimal(1), confidence=Decimal("0.9"))
_NEG = SentimentResult(label="negative", score=Decimal(-1), confidence=Decimal("0.9"))


def test_ruleset_is_versioned() -> None:
    assert IMPACT_RULESET_VERSION == "impact-v1"


def test_classifies_positive_events() -> None:
    assert classify_event("L&T bags ₹15,000 crore order from railways") == EventType.CONTRACT_WIN
    assert classify_event("Infosys Q1 profit beats estimates") == EventType.EARNINGS_BEAT
    assert classify_event("Brokerage upgrades TCS to buy") == EventType.UPGRADE


def test_classifies_negative_events() -> None:
    assert classify_event("SEBI bans firm over disclosure lapse") == EventType.REGULATORY
    assert classify_event("Company defaults on bond, faces insolvency") == EventType.DISTRESS
    assert classify_event("Auditor flags fraud; lawsuit filed") == EventType.FRAUD_LITIGATION


def test_no_event_is_none() -> None:
    assert classify_event("Company to hold annual general meeting next Tuesday") == EventType.NONE
    assert classify_event("") == EventType.NONE


def test_dominant_event_wins_by_magnitude() -> None:
    # A headline with both a mild positive cue and a severe negative one → the severe one leads.
    assert classify_event("Firm wins small order but hit with fraud probe and ban") in (
        EventType.REGULATORY,
        EventType.FRAUD_LITIGATION,
    )


def test_event_dominates_and_sentiment_modulates() -> None:
    scorer = EventImpactScorer()
    win_pos = scorer.score("bags ₹5000 cr order", _POS)
    win_neu = scorer.score("bags ₹5000 cr order", _NEUTRAL)
    assert win_pos > win_neu > Decimal(0)  # positive tone amplifies a positive event


def test_ban_is_strongly_negative() -> None:
    s = EventImpactScorer().score("regulator bans company from trading", _NEG)
    assert s < Decimal(-40)  # base -40 plus negative tone


def test_conflicting_signal_is_muted() -> None:
    # Positive event but negative tone → pulled toward zero (event still leads).
    s = EventImpactScorer().score("wins contract", _NEG)
    assert Decimal(-10) <= s <= Decimal(10)


def test_no_event_falls_back_to_sentiment() -> None:
    scorer = EventImpactScorer()
    assert scorer.score("AGM scheduled next week", _POS) > Decimal(0)
    assert scorer.score("AGM scheduled next week", _NEG) < Decimal(0)
    assert scorer.score("AGM scheduled next week", _NEUTRAL) == Decimal(0)


def test_score_is_clamped_and_decimal() -> None:
    s = EventImpactScorer().score("fraud default insolvency bankruptcy ban probe", _NEG)
    assert isinstance(s, Decimal)
    assert s >= Decimal(-100)  # clamped

"""DevSentiment — the always-on, deterministic lexicon model (QV-044).

The default `ISentimentService` runtime: it runs everywhere (x86 macOS 12 + py3.13, CI) with zero
heavy deps, so the sentiment pipeline (score → `sentiment` table → `NewsScored` → QV-046 factor) is
live in dev while real FinBERT inference is deferred to a capable host (teammate / Docker / EC2 /
CI-Linux). A small curated financial pos/neg word list drives a signed score; deterministic by
construction (golden-tested). All numerics are `Decimal` (money rule).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

from quantvista.news.models import SentimentLabel, SentimentResult

MODEL_VERSION = "dev-lexicon-v1"

# Curated financial-sentiment cues (Loughran-McDonald-flavoured, headline-oriented). Not
# exhaustive — a transparent dev signal, not a substitute for FinBERT. Matched whole-word, folded.
_POSITIVE: frozenset[str] = frozenset(
    {
        "beats",
        "beat",
        "surges",
        "surge",
        "soars",
        "soar",
        "jumps",
        "rally",
        "rallies",
        "gains",
        "gain",
        "wins",
        "win",
        "won",
        "upgrade",
        "upgraded",
        "profit",
        "profits",
        "record",
        "growth",
        "raises",
        "raised",
        "outperform",
        "bullish",
        "strong",
        "expands",
        "approval",
        "approved",
        "dividend",
        "buyback",
        "acquires",
        "acquisition",
        "positive",
    }
)
_NEGATIVE: frozenset[str] = frozenset(
    {
        "misses",
        "miss",
        "plunges",
        "plunge",
        "slumps",
        "falls",
        "fall",
        "drops",
        "drop",
        "downgrade",
        "downgraded",
        "loss",
        "losses",
        "probe",
        "fraud",
        "default",
        "defaults",
        "ban",
        "banned",
        "fine",
        "penalty",
        "lawsuit",
        "cuts",
        "cut",
        "slashes",
        "slash",
        "weak",
        "bearish",
        "warning",
        "warns",
        "recall",
        "resign",
        "resigns",
        "negative",
    }
)
# Confidence saturates once this many cue words are matched (density → certainty proxy).
_CONFIDENCE_SATURATION = Decimal(5)
# Score magnitude below this rounds to neutral (both sides balanced or no cues).
_NEUTRAL_BAND = Decimal("0.0")

_WORD_RE = re.compile(r"[a-z']+")


class DevSentiment:
    """Lexicon `ISentimentService`: deterministic, dependency-free, batch-capable."""

    model_version = MODEL_VERSION

    def classify(self, texts: Sequence[str]) -> Sequence[SentimentResult]:
        return [self._score_one(t) for t in texts]

    def _score_one(self, text: str) -> SentimentResult:
        words = _WORD_RE.findall((text or "").casefold())
        pos = sum(1 for w in words if w in _POSITIVE)
        neg = sum(1 for w in words if w in _NEGATIVE)
        total = pos + neg
        if total == 0:
            return SentimentResult(label="neutral", score=Decimal(0), confidence=Decimal(0))

        score = (Decimal(pos) - Decimal(neg)) / Decimal(total)
        confidence = min(Decimal(1), Decimal(total) / _CONFIDENCE_SATURATION)
        if score > _NEUTRAL_BAND:
            label: SentimentLabel = "positive"
        elif score < -_NEUTRAL_BAND:
            label = "negative"
        else:
            label = "neutral"
        return SentimentResult(label=label, score=score, confidence=confidence)

"""Unit tests for DevSentiment — the deterministic lexicon model (QV-044, always-on dev/CI)."""

from __future__ import annotations

from decimal import Decimal

from quantvista.news.interfaces import ISentimentService
from quantvista.news.models import SentimentResult
from quantvista.news.sentiment import DevSentiment


def _one(text: str) -> SentimentResult:
    (r,) = DevSentiment().classify([text])
    return r


def test_satisfies_the_seam() -> None:
    model = DevSentiment()
    assert isinstance(model, ISentimentService)
    assert model.model_version == "dev-lexicon-v1"


def test_positive_headline() -> None:
    r = _one("Infosys profit beats estimates; company wins record contract and raises guidance")
    assert r.label == "positive"
    assert r.score > 0
    assert Decimal(0) <= r.confidence <= Decimal(1)


def test_negative_headline() -> None:
    r = _one("Regulator launches probe into fraud; company defaults and slashes guidance")
    assert r.label == "negative"
    assert r.score < 0


def test_neutral_when_no_signal() -> None:
    r = _one("Company to hold its annual general meeting next Tuesday in Mumbai")
    assert r.label == "neutral"
    assert r.score == Decimal(0)
    assert r.confidence == Decimal(0)


def test_deterministic_and_batched() -> None:
    texts = ["surges on upgrade", "plunges on downgrade", "neutral filler text"]
    first = DevSentiment().classify(texts)
    second = DevSentiment().classify(texts)
    assert len(first) == 3
    assert [r.label for r in first] == ["positive", "negative", "neutral"]
    assert first == second  # deterministic


def test_score_is_bounded_and_decimal() -> None:
    r = _one("beats beats beats surges wins upgrade profit gains")  # all positive
    assert isinstance(r.score, Decimal) and isinstance(r.confidence, Decimal)
    assert r.score == Decimal(1)  # (pos - neg) / (pos + neg) with no negatives
    assert Decimal(0) < r.confidence <= Decimal(1)


def test_none_or_empty_text_is_neutral() -> None:
    assert _one("").label == "neutral"

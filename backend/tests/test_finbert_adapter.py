"""FinBERTSentiment (QV-044): label/score mapping via an injected fake pipeline (no torch needed),
plus a real ProsusAI/finbert smoke test behind @pytest.mark.finbert (CI-Linux / capable host)."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from typing import Any

import pytest

from quantvista.news.adapters.finbert import FinBERTSentiment, Pipeline
from quantvista.news.interfaces import ISentimentService

_HAS_TORCH = importlib.util.find_spec("torch") is not None


def _fake_pipeline(outputs: list[list[dict[str, Any]]]) -> Pipeline:
    """A pipeline stand-in that echoes canned per-text class distributions (no model/torch)."""

    def _call(texts: list[str]) -> list[list[dict[str, Any]]]:
        assert len(texts) == len(outputs)
        return outputs

    return _call


def _dist(pos: float, neg: float, neu: float) -> list[dict[str, Any]]:
    return [
        {"label": "positive", "score": pos},
        {"label": "negative", "score": neg},
        {"label": "neutral", "score": neu},
    ]


def test_satisfies_the_seam_without_torch() -> None:
    model = FinBERTSentiment(pipeline=_fake_pipeline([]))
    assert isinstance(model, ISentimentService)
    assert model.model_version == "finbert-prosusai-v1"


def test_maps_distribution_to_signed_result() -> None:
    dist = [_dist(0.90, 0.04, 0.06)]
    (r,) = FinBERTSentiment(pipeline=_fake_pipeline(dist)).classify(["Infosys beats estimates"])
    assert r.label == "positive"
    assert r.score == Decimal("0.90") - Decimal("0.04")  # P(pos) - P(neg)
    assert r.confidence == Decimal("0.90")  # winning class prob


def test_negative_and_neutral_argmax() -> None:
    dist = [_dist(0.1, 0.8, 0.1), _dist(0.2, 0.2, 0.6)]
    out = FinBERTSentiment(pipeline=_fake_pipeline(dist)).classify(
        ["probe launched", "AGM scheduled"]
    )
    assert [r.label for r in out] == ["negative", "neutral"]
    assert out[0].score < 0 and out[1].score == Decimal("0.2") - Decimal("0.2")


def test_empty_batch_short_circuits() -> None:
    assert FinBERTSentiment(pipeline=_fake_pipeline([])).classify([]) == []


@pytest.mark.finbert
@pytest.mark.skipif(not _HAS_TORCH, reason="needs the [finbert] extra (torch)")
def test_real_finbert_smoke() -> None:
    # Exercises the ACTUAL ProsusAI/finbert model end-to-end (downloads weights on first run).
    model = FinBERTSentiment()
    pos, neg = model.classify(
        ["Company profit surges and beats estimates", "Regulator opens fraud probe into company"]
    )
    assert pos.label == "positive"
    assert neg.label == "negative"
    assert Decimal(-1) <= pos.score <= Decimal(1)

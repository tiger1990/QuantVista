"""score_news job wiring (QV-044): model factory + task registration + nlp-queue routing."""

from __future__ import annotations

import pytest

from quantvista.core.config import Settings
from quantvista.jobs.celery_app import app
from quantvista.jobs.sentiment import get_sentiment_model, score_news
from quantvista.news.adapters.finbert import FinBERTSentiment
from quantvista.news.sentiment import DevSentiment


def test_factory_returns_dev_by_default() -> None:
    model = get_sentiment_model(Settings(sentiment_model="dev"))
    assert isinstance(model, DevSentiment)
    assert model.model_version == "dev-lexicon-v1"


def test_factory_selects_finbert(monkeypatch: pytest.MonkeyPatch) -> None:
    # Dispatch to FinBERTSentiment WITHOUT loading torch: stub the heavy pipeline builder.
    monkeypatch.setattr(
        "quantvista.news.adapters.finbert.build_finbert_pipeline", lambda: lambda texts: []
    )
    model = get_sentiment_model(Settings(sentiment_model="finbert"))
    assert isinstance(model, FinBERTSentiment)
    assert model.model_version == "finbert-prosusai-v1"


def test_factory_rejects_unknown() -> None:
    with pytest.raises(RuntimeError, match="unknown sentiment_model"):
        get_sentiment_model(Settings(sentiment_model="bogus"))


def test_task_registered_and_routed_to_nlp_queue() -> None:
    assert score_news.name == "quantvista.score_news"
    assert app.conf.task_routes["quantvista.score_news"]["queue"] == "nlp"

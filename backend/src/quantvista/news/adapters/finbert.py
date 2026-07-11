"""FinBERTSentiment — the real `ISentimentService` backed by ProsusAI/finbert (QV-044).

`transformers`+`torch` are the optional `[finbert]` extra and are **lazy-imported** — importing this
module is cheap and safe on the dev box, but constructing `FinBERTSentiment()` (or calling the
default pipeline factory) requires the extra. There is NO torch/onnxruntime wheel for x86_64 macOS
12 + py3.13, so live inference runs only on a capable host (teammate / Docker / EC2 / CI-Linux);
here it is exercised via an injected fake pipeline (unit) and the real model behind
`@pytest.mark.finbert` (CI-Linux). All numerics are `Decimal` (money rule).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any, cast

from quantvista.news.models import SentimentLabel, SentimentResult

MODEL_VERSION = "finbert-prosusai-v1"
_MODEL_ID = "ProsusAI/finbert"

# A pipeline maps a batch of texts → per-text list of {"label", "score"} over all 3 classes.
Pipeline = Callable[[list[str]], list[list[dict[str, Any]]]]

_LABELS: tuple[SentimentLabel, ...] = ("positive", "negative", "neutral")


def build_finbert_pipeline() -> Pipeline:
    """Construct the real HuggingFace text-classification pipeline (needs the `[finbert]` extra)."""
    try:
        from transformers import pipeline  # noqa: PLC0415 — lazy: heavy, optional extra
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "FinBERTSentiment needs the optional ML stack. Install it on a capable host "
            "(no torch wheel for x86 macOS 12 / py3.13): `pip install -e .[finbert]`."
        ) from exc
    # top_k=None → return the full probability distribution over positive/negative/neutral.
    return cast(Pipeline, pipeline("text-classification", model=_MODEL_ID, top_k=None))


class FinBERTSentiment:
    """`ISentimentService` over ProsusAI/finbert. Batched; pipeline injectable for tests."""

    model_version = MODEL_VERSION

    def __init__(self, pipeline: Pipeline | None = None) -> None:
        self._pipe = pipeline if pipeline is not None else build_finbert_pipeline()

    def classify(self, texts: Sequence[str]) -> Sequence[SentimentResult]:
        if not texts:
            return []
        raw = self._pipe(list(texts))
        return [self._to_result(scores) for scores in raw]

    @staticmethod
    def _to_result(scores: list[dict[str, Any]]) -> SentimentResult:
        # scores = [{"label": "positive", "score": 0.9}, {"label": "negative", ...}, {"neutral"...}]
        probs = {str(s["label"]).casefold(): Decimal(str(s["score"])) for s in scores}
        pos = probs.get("positive", Decimal(0))
        neg = probs.get("negative", Decimal(0))
        neu = probs.get("neutral", Decimal(0))
        score = pos - neg  # signed net sentiment in [-1, 1]
        confidence = max(pos, neg, neu)  # the winning class probability
        label: SentimentLabel = _LABELS[_argmax((pos, neg, neu))]
        return SentimentResult(label=label, score=score, confidence=confidence)


def _argmax(values: tuple[Decimal, ...]) -> int:
    best_i, best_v = 0, values[0]
    for i, v in enumerate(values):
        if v > best_v:
            best_i, best_v = i, v
    return best_i

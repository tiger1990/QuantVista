"""score_news (QV-044) — fake model, real Postgres; persist + idempotency + model coexistence.

Proves the SentimentScoringService over the real ``sentiment`` table (0007): rows persist for the
active model_version, re-runs are idempotent (UNIQUE(news_id, model_version) DO UPDATE), a second
model_version coexists per article, and ``NewsScored`` fires after commit.

The dev DB already holds real news rows, and ``score_unscored`` scans ALL unscored news by design
(no universe filter). So each test uses a UNIQUE model_version and cleans up exactly those rows —
assertions are independent of how many other articles happen to be present.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.news.models import SentimentResult
from quantvista.news.services import SentimentScoringService

pytestmark = pytest.mark.integration


class _FixedModel:
    """A deterministic ISentimentService: every text → the same result, tagged by model_version."""

    def __init__(self, model_version: str, result: SentimentResult) -> None:
        self.model_version = model_version
        self._result = result

    def classify(self, texts: Sequence[str]) -> Sequence[SentimentResult]:
        return [self._result for _ in texts]


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object]]] = []

    def publish(self, topic: str, event: dict[str, object]) -> None:
        self.published.append((topic, event))

    def subscribe(self, topic: str, handler: object) -> None: ...


_POS = SentimentResult(label="positive", score=Decimal("0.5"), confidence=Decimal("0.8"))
_NEG = SentimentResult(label="negative", score=Decimal("-0.4"), confidence=Decimal("0.7"))


@dataclass
class _World:
    a: UUID
    b: UUID
    mv: str  # unique model_version for this test
    mv2: str  # a second unique model_version (coexistence)


@pytest.fixture
def world(admin_engine: Engine) -> Iterator[_World]:
    a, b = uuid4(), uuid4()
    mv, mv2 = f"test-{uuid4().hex[:8]}", f"test-{uuid4().hex[:8]}"
    with admin_engine.begin() as conn:
        for nid, head in [(a, "Company profit surges"), (b, "Regulator opens probe")]:
            conn.execute(
                text(
                    "INSERT INTO news (id, headline, summary, published_at) "
                    "VALUES (:id, :h, NULL, now())"
                ),
                {"id": nid, "h": head},
            )
    yield _World(a, b, mv, mv2)
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM sentiment WHERE model_version = ANY(:m)"), {"m": [mv, mv2]})
        conn.execute(text("DELETE FROM news WHERE id = ANY(:i)"), {"i": [a, b]})


def _rows(admin_engine: Engine, news_id: UUID, model_versions: list[str]) -> dict[str, str]:
    sql = text(
        "SELECT model_version, label FROM sentiment WHERE news_id = :n AND model_version = ANY(:m)"
    )
    with admin_engine.connect() as conn:
        result = conn.execute(sql, {"n": news_id, "m": model_versions})
        return {str(r[0]): str(r[1]) for r in result}


def test_scores_persist_and_emit_event(admin_engine: Engine, world: _World) -> None:
    bus = _FakeBus()
    report = SentimentScoringService(_FixedModel(world.mv, _POS), bus).score_unscored(
        batch_id="batch-1"
    )
    assert report.scored == report.scanned >= 2  # every scanned article got a row
    assert _rows(admin_engine, world.a, [world.mv]) == {world.mv: "positive"}
    assert bus.published == [
        (
            "NewsScored",
            {"news_batch": "batch-1", "count": report.scored, "impact_version": "impact-v1"},
        )
    ]


def test_rescore_same_model_is_idempotent(admin_engine: Engine, world: _World) -> None:
    svc = SentimentScoringService(_FixedModel(world.mv, _POS), _FakeBus())
    svc.score_unscored()
    again = svc.score_unscored()  # nothing left unscored for this model_version
    assert again.scanned == 0 and again.scored == 0
    with admin_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM sentiment WHERE news_id = :n AND model_version = :m"),
            {"n": world.a, "m": world.mv},
        ).scalar_one()
    assert n == 1  # no duplicate row


def test_two_model_versions_coexist(admin_engine: Engine, world: _World) -> None:
    SentimentScoringService(_FixedModel(world.mv, _POS), _FakeBus()).score_unscored()
    SentimentScoringService(_FixedModel(world.mv2, _NEG), _FakeBus()).score_unscored()
    assert _rows(admin_engine, world.a, [world.mv, world.mv2]) == {
        world.mv: "positive",
        world.mv2: "negative",
    }


def test_impact_score_persists_and_reflects_event(admin_engine: Engine, world: _World) -> None:
    # QV-045: same (positive) tone on both, so the impact difference comes purely from event type.
    # world.a "Company profit surges" → EARNINGS_BEAT (+30); world.b "Regulator opens probe" → -40.
    SentimentScoringService(_FixedModel(world.mv, _POS), _FakeBus()).score_unscored()

    def _impact(news_id: UUID) -> Decimal:
        with admin_engine.connect() as conn:
            value = conn.execute(
                text(
                    "SELECT impact_score FROM sentiment WHERE news_id = :n AND model_version = :m"
                ),
                {"n": news_id, "m": world.mv},
            ).scalar_one()
        return Decimal(str(value))

    beat = _impact(world.a)  # +30 base + 0.5 tone * 25 = +42.5
    regulatory = _impact(world.b)  # -40 base + 0.5 tone * 25 = -27.5
    assert beat == Decimal("42.5")
    assert regulatory == Decimal("-27.5")
    assert beat > regulatory  # the positive event outranks the regulatory one

"""News ingestion over real Postgres (QV-041) — fake provider (no network).

Proves source_url dedup (idempotent per window, incl. within a run across the market queries), the
NewsIngested emit, and the task under run_job. Cleaned up by source_url prefix / run_key.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs import news as news_mod
from quantvista.jobs.framework import run_key
from quantvista.jobs.news import _run_news
from quantvista.news.models import NewsArticle
from quantvista.news.services import NewsIngestionService

pytestmark = pytest.mark.integration

_PREFIX = "https://qv-test.example/"
_SINCE = datetime(2026, 7, 1, tzinfo=UTC)
_UNTIL = datetime(2026, 7, 1, 2, tzinfo=UTC)


class _FakeNews:
    """Returns the same two articles for every query — so cross-query dedup is exercised."""

    name = "fake"

    def get_news(self, query: str, since: datetime, until: datetime) -> Sequence[NewsArticle]:
        return [
            NewsArticle(
                "Nifty up", "rally", "ET", f"{_PREFIX}a", datetime(2026, 7, 1, 9, tzinfo=UTC)
            ),
            NewsArticle(
                "Sensex up", "gains", "BS", f"{_PREFIX}b", datetime(2026, 7, 1, 10, tzinfo=UTC)
            ),
        ]


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object]]] = []

    def publish(self, topic: str, event: dict[str, object]) -> None:
        self.published.append((topic, event))

    def subscribe(self, topic: str, handler: object) -> None:  # IEventBus member (unused here)
        raise NotImplementedError


@pytest.fixture
def clean(admin_engine: Engine) -> Iterator[None]:
    yield
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM news WHERE source_url LIKE :p"), {"p": f"{_PREFIX}%"})
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "news:%"})


def _news_count(admin_engine: Engine) -> int:
    with admin_engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM news WHERE source_url LIKE :p"), {"p": f"{_PREFIX}%"}
            ).scalar_one()
        )


def test_ingest_dedups_within_and_across_providers_and_runs(
    admin_engine: Engine, clean: None
) -> None:
    bus = _FakeBus()
    # Two providers, each returning the same 2 URLs for 2 queries → 8 fetched, 2 inserted (dedup
    # across queries AND providers on source_url).
    service = NewsIngestionService([_FakeNews(), _FakeNews()], bus)

    report = service.ingest(_SINCE, _UNTIL)
    assert report.fetched == 8 and report.inserted == 2
    assert _news_count(admin_engine) == 2
    assert bus.published[0][0] == "NewsIngested"

    # Re-run over the same window → dedup on source_url → no new rows.
    report2 = service.ingest(_SINCE, _UNTIL)
    assert report2.inserted == 0
    assert _news_count(admin_engine) == 2


def test_ingest_leaves_news_untagged(admin_engine: Engine, clean: None) -> None:
    NewsIngestionService([_FakeNews()], _FakeBus()).ingest(_SINCE, _UNTIL)
    with admin_engine.connect() as conn:
        untagged = conn.execute(
            text("SELECT count(*) FROM news WHERE source_url LIKE :p AND tagged_at IS NULL"),
            {"p": f"{_PREFIX}%"},
        ).scalar_one()
    assert untagged == 2  # tagging (QV-042/094) is a separate step


def test_task_runs_under_run_job(
    admin_engine: Engine, clean: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(news_mod, "get_news_providers", lambda: [_FakeNews()])
    key = run_key("news", "fake", uuid4().hex[:8])
    outcome = _run_news(_UNTIL, key)
    assert outcome.status.value == "succeeded"
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"), {"k": key}
        ).scalar_one()
    assert status == "succeeded"
    assert _news_count(admin_engine) == 2

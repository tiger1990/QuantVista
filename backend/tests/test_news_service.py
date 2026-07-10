"""Unit tests for NewsIngestionService (news.services, QV-041) — DB + provider faked.

Proves the provider-agnostic ingest loop: per-query isolation (one failing query doesn't abort),
counts, and the ``NewsIngested`` emit. DB writes are stubbed; dedup/idempotency is covered by the
integration test.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

import pytest

from quantvista.news import services as news_services
from quantvista.news.models import NewsArticle
from quantvista.news.services import MARKET_QUERIES, NewsIngestionService

SINCE = datetime(2026, 7, 1, tzinfo=UTC)
UNTIL = datetime(2026, 7, 1, 1, tzinfo=UTC)


def _article(url: str) -> NewsArticle:
    return NewsArticle("h", "s", "src", url, datetime(2026, 7, 1, 9, tzinfo=UTC))


class _FakeProvider:
    name = "fake"

    def __init__(self, *, fail_on: str | None = None) -> None:
        self._fail_on = fail_on
        self.calls: list[str] = []

    def get_news(self, query: str, since: datetime, until: datetime) -> Sequence[NewsArticle]:
        self.calls.append(query)
        if query == self._fail_on:
            raise RuntimeError("boom")
        return [
            _article(f"https://ex.com/{query[:3]}-1"),
            _article(f"https://ex.com/{query[:3]}-2"),
        ]


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object]]] = []

    def publish(self, topic: str, event: dict[str, object]) -> None:
        self.published.append((topic, event))

    def subscribe(self, topic: str, handler: object) -> None:  # IEventBus member (unused here)
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real DB: session scope is a no-op; upsert reports every article as inserted."""

    @contextlib.contextmanager
    def _fake_scope() -> Iterator[object]:
        yield object()

    monkeypatch.setattr(news_services, "privileged_session_scope", _fake_scope)
    monkeypatch.setattr(news_services, "upsert_news", lambda _s, articles: len(articles))


def test_ingest_fans_out_over_providers_and_emits_event() -> None:
    providers = [_FakeProvider(), _FakeProvider()]
    bus = _FakeBus()

    report = NewsIngestionService(providers, bus).ingest(SINCE, UNTIL)

    # Each provider is called once per market query.
    assert all(p.calls == list(MARKET_QUERIES) for p in providers)
    assert report.providers == ("fake", "fake")
    assert report.fetched == 2 * len(MARKET_QUERIES) * len(providers)
    assert report.inserted == report.fetched
    assert report.fetches_failed == 0

    assert len(bus.published) == 1
    topic, event = bus.published[0]
    assert topic == "NewsIngested"
    assert event["providers"] == ["fake", "fake"]
    assert event["inserted"] == report.inserted


def test_ingest_isolates_a_failing_provider_query() -> None:
    good = _FakeProvider()
    bad = _FakeProvider(fail_on=MARKET_QUERIES[0])
    bus = _FakeBus()

    report = NewsIngestionService([good, bad], bus).ingest(SINCE, UNTIL)

    # bad's first query blew up; everything else still ingested and the event still fired.
    assert report.fetches_failed == 1
    assert report.fetched == 2 * (2 * len(MARKET_QUERIES) - 1)
    assert report.inserted == report.fetched
    assert bus.published[0][0] == "NewsIngested"

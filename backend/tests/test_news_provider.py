"""Unit tests for the news adapters (news.providers, QV-041) — network-free.

A stubbed ``urlopen`` returns canned payloads for each provider (NewsAPI/GNews/Marketaux/Finnhub),
pinning each parse + mapping without touching the network (mirrors the FRED adapter test).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from quantvista.news.providers import (
    FinnhubProvider,
    GNewsProvider,
    MarketauxProvider,
    NewsApiProvider,
)

WINDOW = (datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 1, 1, tzinfo=UTC))


class _FakeResp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _urlopen_with(payload: Any):  # type: ignore[no-untyped-def]
    data = json.dumps(payload).encode()

    def _open(url: str, timeout: float | None = None) -> _FakeResp:
        return _FakeResp(data)

    return _open


def test_newsapi_provider_maps_articles() -> None:
    payload = {
        "status": "ok",
        "totalResults": 2,
        "articles": [
            {
                "source": {"id": None, "name": "Economic Times"},
                "title": "Nifty hits record high",
                "description": "Benchmark indices rallied.",
                "url": "https://example.com/nifty-record",
                "publishedAt": "2026-07-01T09:30:00Z",
            },
            {  # malformed (no title) → skipped defensively
                "source": {"name": "X"},
                "title": None,
                "url": "https://example.com/bad",
                "publishedAt": "2026-07-01T09:31:00Z",
            },
        ],
    }
    provider = NewsApiProvider("test-key", urlopen=_urlopen_with(payload))

    articles = provider.get_news("Nifty", *WINDOW)

    assert len(articles) == 1
    a = articles[0]
    assert a.headline == "Nifty hits record high"
    assert a.summary == "Benchmark indices rallied."
    assert a.source == "Economic Times"
    assert a.source_url == "https://example.com/nifty-record"
    assert a.published_at == datetime(2026, 7, 1, 9, 30, tzinfo=UTC)
    assert a.language == "en"


def test_newsapi_provider_raises_on_in_body_error() -> None:
    payload = {"status": "error", "code": "rateLimited", "message": "Too many requests"}
    provider = NewsApiProvider("test-key", urlopen=_urlopen_with(payload))

    with pytest.raises(RuntimeError, match="NewsAPI error"):
        provider.get_news("Nifty", *WINDOW)


def test_newsapi_provider_requires_a_key() -> None:
    with pytest.raises(RuntimeError, match="NEWS_API_ORG_API_KEY"):
        NewsApiProvider(None)


def test_gnews_provider_maps_articles() -> None:
    payload = {
        "totalArticles": 1,
        "articles": [
            {
                "title": "Sensex rallies",
                "description": "Broad gains.",
                "url": "https://ex.com/sensex",
                "publishedAt": "2026-07-01T08:00:00Z",
                "source": {"name": "Mint", "url": "https://livemint.com"},
            }
        ],
    }
    articles = GNewsProvider("k", urlopen=_urlopen_with(payload)).get_news("Sensex", *WINDOW)
    assert len(articles) == 1
    assert articles[0].headline == "Sensex rallies"
    assert articles[0].source == "Mint"
    assert articles[0].published_at == datetime(2026, 7, 1, 8, tzinfo=UTC)


def test_marketaux_provider_maps_data_and_falls_back_to_snippet() -> None:
    payload = {
        "data": [
            {
                "title": "Reliance Q1 beat",
                "description": None,
                "snippet": "Profit up 12%.",
                "url": "https://ex.com/ril",
                "published_at": "2026-07-01T07:30:00.000000Z",
                "source": "economictimes.com",
                "entities": [{"symbol": "RELIANCE.NS", "sentiment_score": 0.6}],
            }
        ]
    }
    articles = MarketauxProvider("k", urlopen=_urlopen_with(payload)).get_news("Reliance", *WINDOW)
    assert len(articles) == 1
    assert articles[0].headline == "Reliance Q1 beat"
    assert articles[0].summary == "Profit up 12%."  # description None → snippet
    assert articles[0].source == "economictimes.com"


def test_finnhub_provider_maps_unix_datetime_and_windows() -> None:
    in_window = int(datetime(2026, 7, 1, 0, 30, tzinfo=UTC).timestamp())
    out_window = int(datetime(2026, 7, 5, tzinfo=UTC).timestamp())  # past `until` → filtered
    payload = [
        {"datetime": in_window, "headline": "In window", "source": "Reuters", "url": "u1"},
        {"datetime": out_window, "headline": "Stale", "source": "Reuters", "url": "u2"},
    ]
    articles = FinnhubProvider("k", urlopen=_urlopen_with(payload)).get_news("x", *WINDOW)
    assert [a.headline for a in articles] == ["In window"]  # out-of-window dropped
    assert articles[0].published_at == datetime.fromtimestamp(in_window, tz=UTC)


@pytest.mark.parametrize(
    ("cls", "env"),
    [
        (GNewsProvider, "GNEWS_API_KEY"),
        (MarketauxProvider, "MARKETAUX_API_KEY"),
        (FinnhubProvider, "FINHUB_API_KEY"),
    ],
)
def test_provider_requires_a_key(cls: type, env: str) -> None:
    with pytest.raises(RuntimeError, match=env):
        cls(None)


def test_get_news_providers_builds_enabled_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from quantvista.jobs import news as news_mod

    class _S:
        news_providers = "newsapi,gnews,marketaux,finnhub"
        newsapi_org_api_key = "a"
        gnews_api_key = "b"
        marketaux_api_key = None  # no key → skipped
        finnhub_api_key = "d"

    providers = news_mod.get_news_providers(_S())  # type: ignore[arg-type]
    names = [p.name for p in providers]  # type: ignore[attr-defined]
    assert names == ["newsapi", "gnews", "finnhub"]  # marketaux dropped (no key)


def test_get_news_providers_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    from quantvista.jobs import news as news_mod

    class _S:
        news_providers = "bloomberg"
        newsapi_org_api_key = gnews_api_key = marketaux_api_key = finnhub_api_key = "x"

    with pytest.raises(RuntimeError, match="unknown news provider"):
        news_mod.get_news_providers(_S())  # type: ignore[arg-type]

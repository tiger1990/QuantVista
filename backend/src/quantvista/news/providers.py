"""News provider adapters (QV-041) — the vendor seam's concrete implementations.

Mirrors ``market_data/macro.py``: a small HTTP+JSON base (``ssl`` + **certifi** CA bundle so TLS
works on macOS dev + Linux/CI, retry, **injectable ``urlopen``** for network-free tests) under the
``INewsProvider`` seam. Four dev-tier adapters, all behind the same Protocol so the ingestion
service fans out over them without naming any vendor:

- **NewsAPI.org** (``/v2/everything``) — broad; good Indian business publishers (dev-license only).
- **GNews** (``/api/v4/search``, ``country=in``) — Indian publisher coverage.
- **Marketaux** (``/v1/news/all``, ``countries=in``) — finance-specific + India-aware; also returns
  ``entities`` (stock symbols) + ``sentiment_score`` per article — the seam for QV-042 tagging and a
  comparison signal for QV-044 (not consumed here yet).
- **Finnhub** (``/api/v1/news``, ``category=general``) — general market news (US-centric; low India
  signal, included for completeness).

Every key comes from settings; each adapter raises without its key. All free tiers are **dev-grade**
(NewsAPI is explicitly development-only) — production needs paid tiers, same posture as yfinance.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import certifi

from quantvista.news.models import NewsArticle

_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_GNEWS_URL = "https://gnews.io/api/v4/search"
_MARKETAUX_URL = "https://api.marketaux.com/v1/news/all"
_FINNHUB_URL = "https://finnhub.io/api/v1/news"
_RETRY_BACKOFF_S = 1.5

# NewsAPI /v2/everything searches ALL web content, so a bare market query pulls noise. Scope it to
# Indian financial publishers so it's an India-business source, not a general firehose.
_NEWSAPI_INDIA_DOMAINS = (
    "economictimes.indiatimes.com,moneycontrol.com,livemint.com,"
    "business-standard.com,thehindubusinessline.com,financialexpress.com"
)


# A browser-like User-Agent: Marketaux is behind Cloudflare, which blocks the default
# ``Python-urllib`` signature (Cloudflare error 1010). Harmless for the other providers.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _iso_z(dt: datetime) -> str:
    """UTC ISO-8601 with a trailing ``Z`` (the format GNews/NewsAPI accept for from/to)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _HttpJsonProvider:
    """Shared HTTP+JSON base: certifi trust store + retry. ``urlopen`` injectable for tests."""

    def __init__(self, urlopen: Callable[..., Any] | None = None) -> None:
        self._ctx = ssl.create_default_context(cafile=certifi.where())
        self._urlopen = urlopen or self._default_urlopen

    def _default_urlopen(self, url: str, timeout: float | None = None) -> Any:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        return urllib.request.urlopen(req, timeout=timeout, context=self._ctx)

    def _get_json(self, url: str, *, retries: int = 2) -> Any:
        for attempt in range(1, retries + 1):
            try:
                with self._urlopen(url, timeout=30) as resp:
                    return json.loads(resp.read())
            except Exception:  # transient — retry, else re-raise
                if attempt == retries:
                    raise
                time.sleep(_RETRY_BACKOFF_S)


def _parse_published_at(raw: str) -> datetime:
    """NewsAPI ``publishedAt`` is ISO-8601 UTC (``...Z``); py3.11+ ``fromisoformat`` handles Z."""
    return datetime.fromisoformat(raw)


class NewsApiProvider(_HttpJsonProvider):
    """NewsAPI.org adapter (``/v2/everything``). Free dev tier; key from ``news_api_key``."""

    name = "newsapi"

    def __init__(self, api_key: str | None, *, urlopen: Callable[..., Any] | None = None) -> None:
        if not api_key:
            raise RuntimeError("NewsApiProvider needs a key (set NEWS_API_ORG_API_KEY)")
        super().__init__(urlopen)
        self._api_key = api_key

    def get_news(self, query: str, since: datetime, until: datetime) -> Sequence[NewsArticle]:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "domains": _NEWSAPI_INDIA_DOMAINS,  # scope to Indian financial publishers
                "from": _iso_z(since),
                "to": _iso_z(until),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 100,
                "apiKey": self._api_key,
            }
        )
        data = self._get_json(f"{_NEWSAPI_URL}?{params}")
        if data.get("status") != "ok":  # NewsAPI signals errors in-body with status=error
            raise RuntimeError(f"NewsAPI error: {data.get('code')} {data.get('message')}")

        articles: list[NewsArticle] = []
        for item in data.get("articles", []):
            published = item.get("publishedAt")
            if not item.get("title") or not published:  # skip malformed rows defensively
                continue
            articles.append(
                NewsArticle(
                    headline=item["title"],
                    summary=item.get("description"),
                    source=(item.get("source") or {}).get("name"),
                    source_url=item.get("url"),
                    published_at=_parse_published_at(published),
                )
            )
        return articles


class GNewsProvider(_HttpJsonProvider):
    """GNews.io adapter (``/api/v4/search``, ``country=in``). Key from ``gnews_api_key``."""

    name = "gnews"

    def __init__(self, api_key: str | None, *, urlopen: Callable[..., Any] | None = None) -> None:
        if not api_key:
            raise RuntimeError("GNewsProvider needs a key (set GNEWS_API_KEY)")
        super().__init__(urlopen)
        self._api_key = api_key

    def get_news(self, query: str, since: datetime, until: datetime) -> Sequence[NewsArticle]:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "country": "in",
                "lang": "en",
                "from": _iso_z(since),
                "to": _iso_z(until),
                "max": 100,
                "apikey": self._api_key,
            }
        )
        data = self._get_json(f"{_GNEWS_URL}?{params}")
        articles: list[NewsArticle] = []
        for item in data.get("articles", []):
            published = item.get("publishedAt")
            if not item.get("title") or not published:
                continue
            articles.append(
                NewsArticle(
                    headline=item["title"],
                    summary=item.get("description"),
                    source=(item.get("source") or {}).get("name"),
                    source_url=item.get("url"),
                    published_at=_parse_published_at(published),
                )
            )
        return articles


class MarketauxProvider(_HttpJsonProvider):
    """Marketaux adapter (``/v1/news/all``, ``countries=in``). Finance-specific + India-aware.

    Also returns per-article ``entities`` (stock symbols) + ``sentiment_score`` — used downstream
    (QV-042 tagging / QV-044), not here. Key from ``marketaux_api_key``.
    """

    name = "marketaux"

    def __init__(self, api_key: str | None, *, urlopen: Callable[..., Any] | None = None) -> None:
        if not api_key:
            raise RuntimeError("MarketauxProvider needs a key (set MARKETAUX_API_KEY)")
        super().__init__(urlopen)
        self._api_key = api_key

    def get_news(self, query: str, since: datetime, until: datetime) -> Sequence[NewsArticle]:
        # Marketaux wants published_after/before as `YYYY-MM-DDTHH:MM` (no `Z` — the Z 400s).
        params = urllib.parse.urlencode(
            {
                "countries": "in",
                "language": "en",
                "filter_entities": "true",
                "search": query,
                "published_after": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M"),
                "published_before": until.astimezone(UTC).strftime("%Y-%m-%dT%H:%M"),
                "limit": 100,
                "api_token": self._api_key,
            }
        )
        data = self._get_json(f"{_MARKETAUX_URL}?{params}")
        articles: list[NewsArticle] = []
        for item in data.get("data", []):
            published = item.get("published_at")
            if not item.get("title") or not published:
                continue
            articles.append(
                NewsArticle(
                    headline=item["title"],
                    summary=item.get("description") or item.get("snippet"),
                    source=item.get("source"),
                    source_url=item.get("url"),
                    published_at=_parse_published_at(published),
                )
            )
        return articles


class FinnhubProvider(_HttpJsonProvider):
    """Finnhub adapter (``/api/v1/news``, ``category=general``). US-centric general market news.

    The endpoint returns the latest general market news (no query/window params — both are ignored;
    cross-run dedup on ``source_url`` handles overlap). ``datetime`` is unix seconds. Key from
    ``finnhub_api_key``.
    """

    name = "finnhub"

    def __init__(self, api_key: str | None, *, urlopen: Callable[..., Any] | None = None) -> None:
        if not api_key:
            raise RuntimeError("FinnhubProvider needs a key (set FINHUB_API_KEY)")
        super().__init__(urlopen)
        self._api_key = api_key

    def get_news(self, query: str, since: datetime, until: datetime) -> Sequence[NewsArticle]:
        params = urllib.parse.urlencode({"category": "general", "token": self._api_key})
        data = self._get_json(f"{_FINNHUB_URL}?{params}")
        items = data["data"] if isinstance(data, dict) else data  # REST returns a bare array
        articles: list[NewsArticle] = []
        for item in items:
            epoch = item.get("datetime")
            if not item.get("headline") or not epoch:
                continue
            published = datetime.fromtimestamp(epoch, tz=UTC)
            if not (since <= published <= until):  # endpoint ignores the window — enforce it here
                continue
            articles.append(
                NewsArticle(
                    headline=item["headline"],
                    summary=item.get("summary"),
                    source=item.get("source"),
                    source_url=item.get("url"),
                    published_at=published,
                )
            )
        return articles

"""News feed endpoints (QV-043) — real app + PG + auth. Covers the per-stock feed with the Free-tier
7-day window (older news dropped, other stocks excluded) and the market-wide India-source-first
order. Test stock + news cleaned up by prefix; user/tenant torn down."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from quantvista.api.app import create_app
from quantvista.news.repositories import _INDIA_SOURCES

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
SYMBOL = "ZQNEWS"
URL = "https://qv-news-test.example/"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[tuple[TestClient, str]]:
    client = TestClient(create_app(), base_url="https://testserver")
    email = f"qv-news-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]

    with admin_engine.begin() as conn:
        market_id = conn.execute(text("SELECT id FROM markets WHERE code='NSE'")).scalar_one()
        stock_id = conn.execute(
            text(
                "INSERT INTO stocks (market_id, symbol, company_name, is_active) "
                "VALUES (:m, :s, 'ZQ News Ltd', true) RETURNING id"
            ),
            {"m": market_id, "s": SYMBOL},
        ).scalar_one()
        rows = [
            # (headline, source, url-suffix, age_days, stock_id) — Free window = 7 days
            ("ZQ recent tagged", "Moneycontrol", "a", 2, stock_id),
            ("ZQ old tagged", "Livemint", "b", 30, stock_id),  # beyond 7d → dropped for Free
            ("Other-stock recent", "Reuters", "c", 1, None),  # not tagged to ZQNEWS
        ]
        for headline, source, sfx, age, sid in rows:
            conn.execute(
                text(
                    "INSERT INTO news (headline, source, source_url, published_at, stock_id) "
                    "VALUES (:h, :src, :u, now() - make_interval(days => :age), :sid)"
                ),
                {"h": headline, "src": source, "u": f"{URL}{sfx}", "age": age, "sid": sid},
            )
    yield client, token
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM news WHERE source_url LIKE :p"), {"p": f"{URL}%"})
        conn.execute(text("DELETE FROM stocks WHERE symbol = :s"), {"s": SYMBOL})
        conn.execute(
            text(
                "DELETE FROM tenants WHERE id IN (SELECT m.tenant_id FROM memberships m "
                "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
            ),
            {"e": email},
        )
        conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


def test_per_stock_news_windowed_and_scoped(api: tuple[TestClient, str]) -> None:
    client, token = api
    r = client.get(f"/api/v1/stocks/{SYMBOL}/news", headers=_h(token))
    assert r.status_code == 200
    headlines = [n["headline"] for n in r.json()["data"]]
    # Free 7-day window drops the 30-day-old item; only THIS stock's news (no other-stock row).
    assert headlines == ["ZQ recent tagged"]
    assert r.headers["X-QuantVista-Disclaimer"]


def test_unknown_symbol_returns_empty(api: tuple[TestClient, str]) -> None:
    client, token = api
    r = client.get("/api/v1/stocks/NOSUCHSYM/news", headers=_h(token))
    assert r.status_code == 200 and r.json()["data"] == []


def _is_india(source: str | None) -> bool:
    return source is not None and any(k in source.lower() for k in _INDIA_SOURCES)


def test_market_news_is_india_source_first(api: tuple[TestClient, str]) -> None:
    client, token = api
    data = client.get("/api/v1/news?limit=50", headers=_h(token)).json()["data"]
    assert data  # our seeded rows (+ any ambient) are present
    # Invariant: every India-source row precedes every non-India row (robust to ambient data).
    # Non-trivial by design: Reuters (1d) is newer than Moneycontrol (2d), yet India ranks first.
    flags = [_is_india(n["source"]) for n in data]
    first_non_india = next((i for i, f in enumerate(flags) if not f), len(flags))
    assert all(flags[:first_non_india]) and not any(flags[first_non_india:])

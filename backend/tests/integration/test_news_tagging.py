"""News tagging over real Postgres (QV-042) — seed distinctive stocks + news, tag, assert.

Proves precision over recall: a distinct name tags its stock; an article naming two stocks stays
NULL (ambiguous); an unrelated article stays NULL; re-run is idempotent. Cleaned up by prefix.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.core.db import privileged_session_scope
from quantvista.jobs.framework import run_key
from quantvista.jobs.news import _run_tag
from quantvista.market_data.repositories import stock_catalog
from quantvista.news.services import NewsTaggingService
from quantvista.news.tagging import StockRef

pytestmark = pytest.mark.integration

_SYM_A, _SYM_B = "ZQALPHACORP", "ZQBETAWORKS"
_NAME_A, _NAME_B = "Zqalpha Semiconductor Ltd", "Zqbeta Industries Ltd"
_URL = "https://qv-tag-test.example/"


@pytest.fixture
def seeded(admin_engine: Engine) -> Iterator[dict[str, UUID]]:
    with admin_engine.begin() as conn:
        market_id = conn.execute(text("SELECT id FROM markets WHERE code='NSE'")).scalar_one()
        ids: dict[str, UUID] = {}
        for sym, name in ((_SYM_A, _NAME_A), (_SYM_B, _NAME_B)):
            ids[sym] = conn.execute(
                text(
                    "INSERT INTO stocks (market_id, symbol, company_name, is_active) "
                    "VALUES (:m, :s, :n, true) RETURNING id"
                ),
                {"m": market_id, "s": sym, "n": name},
            ).scalar_one()
        articles = [
            ("Zqalpha Semiconductor posts record profit", f"{_URL}a"),  # → A
            (
                "Zqalpha Semiconductor and Zqbeta Industries in merger talks",
                f"{_URL}b",
            ),  # ambiguous
            ("Global markets steady amid rate worries", f"{_URL}c"),  # unmatched
        ]
        for headline, url in articles:
            conn.execute(
                text(
                    "INSERT INTO news (headline, source_url, published_at) VALUES (:h, :u, now())"
                ),
                {"h": headline, "u": url},
            )
    yield ids
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM news WHERE source_url LIKE :p"), {"p": f"{_URL}%"})
        conn.execute(
            text("DELETE FROM stocks WHERE symbol IN (:a, :b)"), {"a": _SYM_A, "b": _SYM_B}
        )
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE 'tag_news:%'"))


def _stocks_of(admin_engine: Engine, url: str) -> set[UUID]:
    """The stock_ids linked to a news article via news_stocks (QV-094)."""
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ns.stock_id FROM news_stocks ns "
                "JOIN news n ON n.id = ns.news_id WHERE n.source_url = :u"
            ),
            {"u": url},
        ).all()
    return {cast("UUID", r[0]) for r in rows}


def _tag() -> None:
    with privileged_session_scope() as session:
        catalog = [
            StockRef(c.stock_id, c.symbol, c.isin, c.company_name) for c in stock_catalog(session)
        ]
        NewsTaggingService(catalog).tag_untagged(session)


def test_tags_every_named_stock(admin_engine: Engine, seeded: dict[str, UUID]) -> None:
    _tag()
    # Distinct name → its stock; a two-stock article → BOTH (QV-094); no match → no links.
    assert _stocks_of(admin_engine, f"{_URL}a") == {seeded[_SYM_A]}
    assert _stocks_of(admin_engine, f"{_URL}b") == {seeded[_SYM_A], seeded[_SYM_B]}
    assert _stocks_of(admin_engine, f"{_URL}c") == set()


def test_tagging_is_idempotent(admin_engine: Engine, seeded: dict[str, UUID]) -> None:
    _tag()
    with privileged_session_scope() as session:
        catalog = [
            StockRef(c.stock_id, c.symbol, c.isin, c.company_name) for c in stock_catalog(session)
        ]
        report2 = NewsTaggingService(catalog).tag_untagged(session)  # all now tagged_at set
    assert report2.tagged == 0 and report2.links == 0  # nothing left to process
    assert _stocks_of(admin_engine, f"{_URL}b") == {seeded[_SYM_A], seeded[_SYM_B]}  # unchanged


def test_task_runs_under_run_job(admin_engine: Engine, seeded: dict[str, UUID]) -> None:
    key = run_key("tag_news", uuid4().hex[:8])
    outcome = _run_tag(key)
    assert outcome.status.value == "succeeded"
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"), {"k": key}
        ).scalar_one()
    assert status == "succeeded"
    assert _stocks_of(admin_engine, f"{_URL}a") == {seeded[_SYM_A]}

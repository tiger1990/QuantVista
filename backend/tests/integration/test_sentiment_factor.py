"""SentimentFactor / sentiment_as_of over real Postgres (QV-046) — PIT safety + score wire-up.

Seeds a 2-stock sector (fundamentals + indicators so they score) and tags news with sentiment
``impact_score``. Proves: the sentiment signal is PIT-bounded (future news + not-yet-known sentiment
excluded), and it flows into ``scores.sentiment_score`` + the decomposition. Cleaned up by ids.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.context import ScoringContext
from quantvista.analytics.scoring import compute_universe
from quantvista.market_data.fundamentals import record_fundamental_version

pytestmark = pytest.mark.integration

_AS_OF = date(2026, 7, 11)
_KNOWN = datetime(2026, 7, 10, 12, tzinfo=UTC)  # sentiment/fundamentals known before as_of
_IND_DATE = date(2026, 7, 10)
_SEED = {  # symbol: (pe, pb, roe, roce, de), (ret_3m, ret_6m, ret_12m, beta, vol)
    "AAA": ((10, 2.0, 0.25, 0.22, 0.30), (0.08, 0.15, 0.30, 0.9, 0.20)),
    "BBB": ((20, 4.0, 0.15, 0.14, 0.60), (0.02, 0.05, 0.12, 1.2, 0.30)),
}


def _tag_news(
    conn: Connection,
    stock_id: UUID,
    *,
    published: date,
    impact: float,
    created_at: datetime = _KNOWN,
) -> None:
    news_id = uuid4()
    conn.execute(
        text("INSERT INTO news (id, headline, published_at) VALUES (:id, 'H', :p)"),
        {"id": news_id, "p": datetime.combine(published, datetime.min.time(), tzinfo=UTC)},
    )
    conn.execute(
        text("INSERT INTO news_stocks (news_id, stock_id) VALUES (:n, :s)"),
        {"n": news_id, "s": stock_id},
    )
    conn.execute(
        text(
            "INSERT INTO sentiment (news_id, label, score, confidence, impact_score, "
            "model_version, created_at) VALUES (:n, 'neutral', 0, 0, :imp, 'dev-lexicon-v1', :c)"
        ),
        {"n": news_id, "imp": Decimal(str(impact)), "c": created_at},
    )


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[dict[str, UUID]]:
    market_id = uuid4()
    ids: dict[str, UUID] = {sym: uuid4() for sym in _SEED}
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        for sym, sid in ids.items():
            (pe, pb, roe, roce, de), (r3, r6, r12, beta, vol) = _SEED[sym]
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :s, 'Co', 'IT')"
                ),
                {"id": sid, "m": market_id, "s": sym},
            )
            with Session(bind=conn) as session:
                record_fundamental_version(
                    session,
                    sid,
                    date(2025, 12, 31),
                    "quarterly",
                    {
                        "pe": Decimal(str(pe)),
                        "pb": Decimal(str(pb)),
                        "roe": Decimal(str(roe)),
                        "roce": Decimal(str(roce)),
                        "debt_equity": Decimal(str(de)),
                    },
                    knowledge_time=_KNOWN,
                )
                session.commit()
            conn.execute(
                text(
                    "INSERT INTO technical_indicators "
                    "(stock_id, date, ret_3m, ret_6m, ret_12m, beta_1y, vol_30d) "
                    "VALUES (:s, :d, :r3, :r6, :r12, :b, :v)"
                ),
                {"s": sid, "d": _IND_DATE, "r3": r3, "r6": r6, "r12": r12, "b": beta, "v": vol},
            )
    yield ids
    idlist = list(ids.values())
    with admin_engine.begin() as conn:
        news_ids = [
            r[0]
            for r in conn.execute(
                text("SELECT news_id FROM news_stocks WHERE stock_id = ANY(:i)"), {"i": idlist}
            )
        ]
        if news_ids:  # deleting news cascades to sentiment + news_stocks (ON DELETE CASCADE)
            conn.execute(text("DELETE FROM news WHERE id = ANY(:n)"), {"n": news_ids})
        for tbl in ("factor_values", "scores", "technical_indicators", "fundamentals"):
            conn.execute(text(f"DELETE FROM {tbl} WHERE stock_id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def test_sentiment_as_of_is_pit_bounded(admin_engine: Engine, universe: dict[str, UUID]) -> None:
    a = universe["AAA"]
    with admin_engine.begin() as conn:
        _tag_news(conn, a, published=date(2026, 7, 9), impact=50)  # visible: past, known
        _tag_news(conn, a, published=date(2026, 7, 20), impact=-100)  # future news → excluded
        _tag_news(  # past news but sentiment scored AFTER as_of → not yet known → excluded
            conn,
            a,
            published=date(2026, 7, 8),
            impact=-100,
            created_at=datetime(2026, 7, 15, tzinfo=UTC),
        )
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        signal = ScoringContext(session, _AS_OF, [a]).sentiment_as_of(a, _AS_OF)
    assert signal == 50.0  # only the one visible, known article


def test_sentiment_flows_into_scores(admin_engine: Engine, universe: dict[str, UUID]) -> None:
    a, b = universe["AAA"], universe["BBB"]
    with admin_engine.begin() as conn:
        _tag_news(conn, a, published=date(2026, 7, 10), impact=80)  # good news
        _tag_news(conn, b, published=date(2026, 7, 10), impact=-80)  # bad news
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        scores = {s.stock_id: s for s in compute_universe(session, [a, b], _AS_OF)}

    sent_a, sent_b = scores[a].sentiment, scores[b].sentiment
    assert sent_a is not None and sent_b is not None
    assert "sentiment" in scores[a].decomposition  # contributes to the composite
    assert sent_a > sent_b  # good-news stock ranks higher on sentiment
    # decomposition still sums to composite with the sentiment category now included
    assert sum(scores[a].decomposition.values()) == pytest.approx(scores[a].composite, abs=0.01)

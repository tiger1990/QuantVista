"""ScoreEngine end-to-end over real Postgres (QV-029) — seeded 3-stock sector.

Seeds fundamentals (PIT) + indicators for a small sector, runs compute_universe with ALL_FACTORS,
persists, and asserts: a scores row + a factor_values decomposition per stock, composite in [0,100]
summing to its decomposition, coverage, sentiment NULL, and idempotent re-run. Cleaned up by ids.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.factors import ALL_FACTORS
from quantvista.analytics.repositories import upsert_factor_values, upsert_scores
from quantvista.analytics.scoring import ScoreEngine
from quantvista.market_data.fundamentals import record_fundamental_version

pytestmark = pytest.mark.integration

_PERIOD = date(2025, 12, 31)
_KNOWN = datetime(2026, 1, 15, tzinfo=UTC)
_AS_OF = date(2026, 1, 20)
_IND_DATE = date(2026, 1, 15)

# symbol: (pe, pb, roe, roce, de) + (ret_3m, ret_6m, ret_12m, beta_1y, vol_30d)
_SEED = {
    "AAA": ((10, 2.0, 0.25, 0.22, 0.30), (0.08, 0.15, 0.30, 0.9, 0.20)),
    "BBB": ((20, 4.0, 0.15, 0.14, 0.60), (0.02, 0.05, 0.12, 1.2, 0.30)),
    "CCC": ((15, 3.0, 0.20, 0.18, 0.45), (0.05, 0.10, 0.20, 1.0, 0.25)),
}


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[list[UUID]]:
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
                    _PERIOD,
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
    yield list(ids.values())
    with admin_engine.begin() as conn:
        idlist = list(ids.values())
        for tbl in ("factor_values", "scores", "technical_indicators", "fundamentals"):
            conn.execute(text(f"DELETE FROM {tbl} WHERE stock_id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def _persist(admin_engine: Engine, universe: list[UUID]) -> int:
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        scores = ScoreEngine().compute_universe(session, universe, _AS_OF)
        n_fv = upsert_factor_values(session, scores)
        upsert_scores(session, scores)
        session.commit()
    return n_fv


def test_scores_and_decomposition_persist(admin_engine: Engine, universe: list[UUID]) -> None:
    n_fv = _persist(admin_engine, universe)
    assert n_fv == len(universe) * len(ALL_FACTORS)  # 3 × 10 factor_values rows

    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT stock_id, fundamental_score, momentum_score, quality_score, risk_score, "
                "sentiment_score, composite_score, coverage, weights_version, model_version "
                "FROM scores WHERE stock_id = ANY(:i)"
            ),
            {"i": universe},
        ).all()
    assert len(rows) == len(universe)
    for r in rows:
        assert 0 <= float(r.composite_score) <= 100
        assert r.sentiment_score is None  # no sentiment factor yet
        assert float(r.coverage) == 100.0  # all 10 factors present
        assert (r.weights_version, r.model_version) == ("v1", "score-v1")
        # decomposition sums to composite (re-normalized weights over the 4 scored categories)
        weighted = (
            0.40 * float(r.fundamental_score)
            + 0.20 * float(r.momentum_score)
            + 0.20 * float(r.quality_score)
            + 0.10 * float(r.risk_score)
        ) / (0.40 + 0.20 + 0.20 + 0.10)
        assert float(r.composite_score) == pytest.approx(weighted, abs=0.01)


def test_rescore_is_idempotent(admin_engine: Engine, universe: list[UUID]) -> None:
    _persist(admin_engine, universe)
    _persist(admin_engine, universe)  # re-run same date
    with admin_engine.connect() as conn:
        n_scores = conn.execute(
            text("SELECT count(*) FROM scores WHERE stock_id = ANY(:i)"), {"i": universe}
        ).scalar_one()
        n_fv = conn.execute(
            text("SELECT count(*) FROM factor_values WHERE stock_id = ANY(:i)"), {"i": universe}
        ).scalar_one()
    assert n_scores == len(universe)  # overwritten, not duplicated
    assert n_fv == len(universe) * len(ALL_FACTORS)

"""compute_factors + compute_scores jobs over real Postgres (QV-030).

Proves the two-stage pipeline: compute_factors persists the canonical factor_values snapshot + emits
FactorsComputed (post-commit); compute_scores reads that committed snapshot, blends it, persists
scores + emits ScoresComputed. Both idempotent. Throwaway NIFTY200 universe on a unique market.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.factors import ALL_FACTORS, FactorCategory
from quantvista.core.events import get_event_bus, reset_event_bus
from quantvista.jobs.framework import run_key
from quantvista.jobs.scoring import _run_factors, _run_scores
from quantvista.market_data.fundamentals import record_fundamental_version

pytestmark = pytest.mark.integration

# Factors available from seeded fundamentals+indicators (no news → sentiment factor excluded).
_DATA_FACTORS = sum(1 for f in ALL_FACTORS if f.category is not FactorCategory.SENTIMENT)

_PERIOD = date(2025, 12, 31)
_KNOWN = datetime(2026, 1, 15, tzinfo=UTC)
_AS_OF = date(2026, 1, 20)
_IND_DATE = date(2026, 1, 15)
_SEED = {
    "AAA": ((10, 2.0, 0.25, 0.22, 0.30), (0.08, 0.15, 0.30, 0.9, 0.20)),
    "BBB": ((20, 4.0, 0.15, 0.14, 0.60), (0.02, 0.05, 0.12, 1.2, 0.30)),
    "CCC": ((15, 3.0, 0.20, 0.18, 0.45), (0.05, 0.10, 0.20, 1.0, 0.25)),
}


@pytest.fixture(autouse=True)
def _reset_bus() -> Iterator[None]:
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[tuple[str, list[UUID]]]:
    market_id = uuid4()
    ids = {sym: uuid4() for sym in _SEED}
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
            conn.execute(
                text(
                    "INSERT INTO index_constituents (id, index_code, stock_id, effective_from) "
                    "VALUES (gen_random_uuid(), 'NIFTY200', :s, '2020-01-01')"
                ),
                {"s": sid},
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
        market = str(
            conn.execute(
                text("SELECT code FROM markets WHERE id=:m"), {"m": market_id}
            ).scalar_one()
        )
    yield market, list(ids.values())
    with admin_engine.begin() as conn:
        idlist = list(ids.values())
        for tbl in ("factor_values", "scores", "technical_indicators", "fundamentals"):
            conn.execute(text(f"DELETE FROM {tbl} WHERE stock_id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM index_constituents WHERE stock_id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})
        conn.execute(
            text("DELETE FROM jobs_runs WHERE run_key LIKE 'fac:%' OR run_key LIKE 'score:%'")
        )


def _count(admin_engine: Engine, table: str, ids: list[UUID]) -> int:
    with admin_engine.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE stock_id = ANY(:i)"), {"i": ids}
            ).scalar_one()
        )


def test_factors_then_scores_pipeline(
    admin_engine: Engine, universe: tuple[str, list[UUID]]
) -> None:
    market, ids = universe
    events: list[tuple[str, dict[str, object]]] = []
    for topic in ("FactorsComputed", "ScoresComputed"):
        get_event_bus().subscribe(topic, lambda e, t=topic: events.append((t, e["payload"])))

    # Stage 1: compute_factors → factor_values snapshot + FactorsComputed (post-commit).
    out_f = _run_factors(market, _AS_OF, run_key("fac", market, "t1"))
    assert out_f.status.value == "succeeded"
    # No news seeded → the QV-046 sentiment factor is unavailable; expect the non-sentiment factors.
    assert _count(admin_engine, "factor_values", ids) == len(ids) * _DATA_FACTORS  # 3×10
    assert _count(admin_engine, "scores", ids) == 0  # scores NOT written by compute_factors
    assert (
        "FactorsComputed",
        {
            "market": market,
            "date": _AS_OF.isoformat(),
            "model_version": "score-v1",
            "stock_count": 3,
            "factor_count": 30,
        },
    ) in events

    # Stage 2: compute_scores reads the committed snapshot back → scores + ScoresComputed.
    out_s = _run_scores(market, _AS_OF, run_key("score", market, "t1"))
    assert out_s.status.value == "succeeded"
    assert _count(admin_engine, "scores", ids) == len(ids)
    fired = {t: p for t, p in events}
    assert fired["ScoresComputed"] == {
        "universe": market,
        "date": _AS_OF.isoformat(),
        "model_version": "score-v1",
        "count": 3,
    }
    with admin_engine.connect() as conn:
        composite = conn.execute(
            text("SELECT composite_score FROM scores WHERE stock_id = :s"), {"s": ids[0]}
        ).scalar_one()
    assert 0 <= float(composite) <= 100


def test_jobs_are_idempotent(admin_engine: Engine, universe: tuple[str, list[UUID]]) -> None:
    market, ids = universe
    for _ in range(2):
        _run_factors(market, _AS_OF, run_key("fac", market, "same"))
        _run_scores(market, _AS_OF, run_key("score", market, "same"))
    assert _count(admin_engine, "factor_values", ids) == len(ids) * _DATA_FACTORS  # no dup
    assert _count(admin_engine, "scores", ids) == len(ids)

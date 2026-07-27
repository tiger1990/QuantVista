"""PIT data-access for backtests (QV-063) — real Postgres.

Proves the ``BacktestDataAccess`` seam is a look-ahead firewall: at ``as_of`` it ranks the universe
and reads returns from ONLY data knowable by end of ``as_of``. The leakage regression mirrors QV-037
(inject post-``as_of`` trap → ranking unchanged; "trap has teeth" once knowable). Runs in the
required ``backend-rls`` gate. Throwaway rows, cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.backtest_data import BacktestDataAccess
from quantvista.market_data.fundamentals import record_fundamental_version

pytestmark = pytest.mark.integration

_PERIOD = date(2025, 12, 31)
_PRE_KNOWLEDGE = datetime(2026, 1, 5, tzinfo=UTC)
_TRAP_KNOWLEDGE = datetime(2026, 2, 10, tzinfo=UTC)
_PRE_INDICATOR = date(2026, 1, 10)
_TRAP_INDICATOR = date(2026, 2, 15)
EARLY = date(2026, 1, 20)
LATE = date(2026, 3, 15)

# Pre-as_of, cross-sectionally varied (ret_6m, beta_1y, pe) → a well-defined ranking.
_SEED = [("0.05", "1.0", "10"), ("0.10", "1.2", "15"), ("0.02", "0.8", "20")]
# Extreme post-as_of trap values that reorder the ranking IF they ever leaked.
_TRAP = [("0.90", "2.5", "3"), ("0.80", "0.3", "40"), ("0.70", "2.0", "5")]


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[list[UUID]]:
    market_id = uuid4()
    stock_ids = [uuid4() for _ in _SEED]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"BT{uuid4().hex[:6]}"},
        )
        for i, sid in enumerate(stock_ids):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :sym, 'Co', 'IT')"
                ),
                {"id": sid, "m": market_id, "sym": f"BT{i}{uuid4().hex[:4]}"},
            )
        with Session(bind=conn) as session:
            for sid, (_, _, pe) in zip(stock_ids, _SEED, strict=True):
                record_fundamental_version(
                    session,
                    sid,
                    _PERIOD,
                    "quarterly",
                    {"pe": Decimal(pe)},
                    knowledge_time=_PRE_KNOWLEDGE,
                )
            session.commit()
        conn.execute(
            text(
                "INSERT INTO technical_indicators (stock_id, date, ret_6m, beta_1y) "
                "VALUES (:s, :d, :r, :b)"
            ),
            [
                {"s": sid, "d": _PRE_INDICATOR, "r": Decimal(ret), "b": Decimal(beta)}
                for sid, (ret, beta, _) in zip(stock_ids, _SEED, strict=True)
            ],
        )
        # A few adjusted-close bars pre-EARLY + one post-EARLY (the returns firewall check).
        rows = []
        for j, sid in enumerate(stock_ids):
            for d in range(6):  # 2026-01-10 .. 2026-01-15 (all <= EARLY)
                px = Decimal(str(100 + j * 10 + d))
                rows.append({"s": sid, "d": date(2026, 1, 10) + timedelta(days=d), "c": px})
            rows.append({"s": sid, "d": _TRAP_INDICATOR, "c": Decimal("999")})  # post-EARLY bar
        conn.execute(
            text(
                "INSERT INTO daily_prices "
                "(stock_id, date, close, adj_close, high, low, volume, source) "
                "VALUES (:s, :d, :c, :c, :c, :c, 1000, 'seed')"
            ),
            rows,
        )
    yield stock_ids
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:s)"), {"s": stock_ids})
        conn.execute(
            text("DELETE FROM technical_indicators WHERE stock_id = ANY(:s)"), {"s": stock_ids}
        )
        conn.execute(text("DELETE FROM fundamentals WHERE stock_id = ANY(:s)"), {"s": stock_ids})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:s)"), {"s": stock_ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def _inject_trap(admin_engine: Engine, stock_ids: list[UUID]) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO technical_indicators (stock_id, date, ret_6m, beta_1y) "
                "VALUES (:s, :d, :r, :b)"
            ),
            [
                {"s": sid, "d": _TRAP_INDICATOR, "r": Decimal(ret), "b": Decimal(beta)}
                for sid, (ret, beta, _) in zip(stock_ids, _TRAP, strict=True)
            ],
        )
        with Session(bind=conn) as session:
            for sid, (_, _, pe) in zip(stock_ids, _TRAP, strict=True):
                record_fundamental_version(
                    session,
                    sid,
                    _PERIOD,
                    "quarterly",
                    {"pe": Decimal(pe)},
                    knowledge_time=_TRAP_KNOWLEDGE,
                )
            session.commit()


def _ranked(
    admin_engine: Engine,
    universe: list[UUID],
    as_of: date,
    *,
    rank_by: str = "composite",
    top_n: int = 3,
) -> list[UUID]:
    with admin_engine.connect() as conn, Session(bind=conn) as s:
        return BacktestDataAccess(s).ranked_universe(as_of, universe, rank_by=rank_by, top_n=top_n)


# --- selection logic --------------------------------------------------------


def test_ranked_universe_top_n_and_metric(admin_engine: Engine, universe: list[UUID]) -> None:
    top1 = _ranked(admin_engine, universe, EARLY, top_n=1)
    assert len(top1) == 1  # top_n caps the list
    full = _ranked(admin_engine, universe, EARLY)
    assert set(full) <= set(universe) and len(full) == 3  # all scored names, ranked


def test_ranked_universe_deterministic(admin_engine: Engine, universe: list[UUID]) -> None:
    assert _ranked(admin_engine, universe, EARLY) == _ranked(admin_engine, universe, EARLY)


def test_ranked_universe_rejects_bad_metric(admin_engine: Engine, universe: list[UUID]) -> None:
    with (
        admin_engine.connect() as conn,
        Session(bind=conn) as s,
        pytest.raises(ValueError, match="rank_by"),
    ):
        BacktestDataAccess(s).ranked_universe(EARLY, universe, rank_by="astrology", top_n=3)


# --- the firewall (leakage regression) --------------------------------------


def test_ranking_unchanged_by_post_as_of_data(admin_engine: Engine, universe: list[UUID]) -> None:
    baseline = _ranked(admin_engine, universe, EARLY, rank_by="momentum")
    assert len(baseline) == 3  # non-vacuous: real ranking computed

    _inject_trap(admin_engine, universe)
    after = _ranked(admin_engine, universe, EARLY, rank_by="momentum")
    assert after == baseline  # post-as_of trap invisible at EARLY → no look-ahead


def test_trap_has_teeth_once_knowable(admin_engine: Engine, universe: list[UUID]) -> None:
    _inject_trap(admin_engine, universe)
    early = _ranked(admin_engine, universe, EARLY, rank_by="momentum")
    late = _ranked(admin_engine, universe, LATE, rank_by="momentum")
    assert early != late  # LATE sees the trap → ranking moves (guard is non-vacuous)


def test_returns_as_of_has_no_future_bar(admin_engine: Engine, universe: list[UUID]) -> None:
    with admin_engine.connect() as conn, Session(bind=conn) as s:
        rm = BacktestDataAccess(s).returns_as_of(EARLY, universe)
    assert len(rm.dates) > 0
    assert max(rm.dates) <= EARLY  # the post-EARLY bar (2026-02-15) is invisible

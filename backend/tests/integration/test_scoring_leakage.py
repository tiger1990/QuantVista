"""Score-level look-ahead / leakage regression (QV-037) — real Postgres.

The permanent guard (``05`` §1.1): the FULL scoring pipeline (cross-sectional normalization +
blend), not just an individual factor, uses ONLY data knowable at ``as_of``. A counterfactual —
compute scores as-of ``EARLY``, inject post-``as_of`` trap data (future-dated indicators + a
later-knowledge-time fundamentals restatement, extreme values), recompute as-of ``EARLY`` — and
every score must be identical. A companion "trap has teeth" test proves the trap is impactful,
so the guard is non-vacuous.

Runs in the required ``backend-rls`` CI gate (``pytest -m integration``, mandatory Postgres) — a DB
outage fails that job rather than silently skipping, so this guard is effectively non-skippable.
Throwaway rows, cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.scoring import StockScore, compute_universe
from quantvista.market_data.fundamentals import record_fundamental_version

pytestmark = pytest.mark.integration

_PERIOD = date(2025, 12, 31)
_PRE_KNOWLEDGE = datetime(2026, 1, 5, tzinfo=UTC)  # original filing known (before EARLY)
_TRAP_KNOWLEDGE = datetime(2026, 2, 10, tzinfo=UTC)  # restatement known (after EARLY)
_PRE_INDICATOR = date(2026, 1, 10)  # indicator dated on/before EARLY
_TRAP_INDICATOR = date(2026, 2, 15)  # indicator dated after EARLY
EARLY = date(2026, 1, 20)
LATE = date(2026, 3, 15)  # both trap data now knowable

# Pre-as_of, cross-sectionally varied: (ret_6m, beta_1y, pe).
_SEED: list[tuple[str, str, str]] = [
    ("0.05", "1.0", "10"),
    ("0.10", "1.2", "15"),
    ("0.02", "0.8", "20"),
]
# Extreme post-as_of trap values that WOULD move percentiles/scores if they ever leaked.
_TRAP: list[tuple[str, str, str]] = [
    ("0.90", "2.5", "3"),
    ("0.80", "0.3", "40"),
    ("0.70", "2.0", "5"),
]


@dataclass(frozen=True)
class _Scored:
    composite: float
    fundamental: float | None
    momentum: float | None
    quality: float | None
    risk: float | None
    coverage: float


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 6)


def _scores_by_stock(scores: list[StockScore]) -> dict[UUID, _Scored]:
    return {
        s.stock_id: _Scored(
            round(s.composite, 6),
            _r(s.fundamental),
            _r(s.momentum),
            _r(s.quality),
            _r(s.risk),
            round(s.coverage, 6),
        )
        for s in scores
    }


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
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        for i, sid in enumerate(stock_ids):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :sym, 'Co', 'IT')"
                ),
                {"id": sid, "m": market_id, "sym": f"S{i}{uuid4().hex[:4]}"},
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
    yield stock_ids
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM technical_indicators WHERE stock_id = ANY(:s)"), {"s": stock_ids}
        )
        conn.execute(text("DELETE FROM fundamentals WHERE stock_id = ANY(:s)"), {"s": stock_ids})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:s)"), {"s": stock_ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def _inject_trap(admin_engine: Engine, stock_ids: list[UUID]) -> None:
    """Post-as_of data that must be invisible at EARLY (future indicator + later-knowledge pe)."""
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


def test_scores_unchanged_by_post_as_of_data(admin_engine: Engine, universe: list[UUID]) -> None:
    """The core guard: post-``as_of`` data leaves scores as-of ``EARLY`` byte-identical."""
    with admin_engine.connect() as conn, Session(bind=conn) as s:
        baseline = _scores_by_stock(compute_universe(s, universe, EARLY))

    # Non-vacuous: real scores with real coverage were computed (can't pass on empty data).
    assert len(baseline) == len(universe)
    assert all(v.coverage > 0 for v in baseline.values())

    _inject_trap(admin_engine, universe)

    with admin_engine.connect() as conn, Session(bind=conn) as s:
        with_trap = _scores_by_stock(compute_universe(s, universe, EARLY))

    assert with_trap == baseline  # scoring ignored every post-as_of datum → no leakage


def test_trap_data_moves_scores_once_knowable(admin_engine: Engine, universe: list[UUID]) -> None:
    """The trap has teeth: as-of ``LATE`` it moves scores, so the guard is meaningful."""
    _inject_trap(admin_engine, universe)
    with admin_engine.connect() as conn, Session(bind=conn) as s:
        early = _scores_by_stock(compute_universe(s, universe, EARLY))
        late = _scores_by_stock(compute_universe(s, universe, LATE))
    assert any(early[k].composite != late[k].composite for k in universe)

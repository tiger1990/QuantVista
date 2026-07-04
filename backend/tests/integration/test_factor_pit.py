"""Factor point-in-time / look-ahead leakage test (QV-028) — real Postgres.

The structural bias defence (05 §1.1), proven: at an `as_of`, a factor sees ONLY data knowable then.
  - fundamentals: a restatement filed at a LATER knowledge-time is invisible (bitemporal, QV-021);
  - indicators: a row dated AFTER `as_of` is invisible (`date <= as_of`).
Throwaway stock, cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.context import ScoringContext
from quantvista.analytics.factors import PEFactor, Return6MFactor
from quantvista.market_data.fundamentals import record_fundamental_version

pytestmark = pytest.mark.integration

_PERIOD = date(2025, 12, 31)
T_EARLY = datetime(2026, 1, 15, tzinfo=UTC)  # original filing known
T_LATE = datetime(2026, 2, 10, tzinfo=UTC)  # restatement known
_BEFORE_RESTATE = date(2026, 1, 20)  # as_of between the two knowledge-times
_AFTER_RESTATE = date(2026, 2, 15)  # as_of after the restatement is known


@pytest.fixture
def stock(admin_engine: Engine) -> Iterator[UUID]:
    market_id, stock_id = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        conn.execute(
            text(
                "INSERT INTO stocks (id, market_id, symbol, company_name) "
                "VALUES (:id, :m, 'AAA', 'Co')"
            ),
            {"id": stock_id, "m": market_id},
        )
        # A bitemporal restatement: pe 10 known T_EARLY, corrected to 12 known T_LATE.
        with Session(bind=conn) as session:
            record_fundamental_version(
                session,
                stock_id,
                _PERIOD,
                "quarterly",
                {"pe": Decimal("10")},
                knowledge_time=T_EARLY,
            )
            record_fundamental_version(
                session,
                stock_id,
                _PERIOD,
                "quarterly",
                {"pe": Decimal("12")},
                knowledge_time=T_LATE,
            )
            session.commit()
        # Indicators: a row on/before as_of (ret_6m 0.05) and a FUTURE row (0.20) that must not leak

        conn.execute(
            text(
                "INSERT INTO technical_indicators (stock_id, date, ret_6m, beta_1y) "
                "VALUES (:s, :d, :r, :b)"
            ),
            [
                {"s": stock_id, "d": date(2026, 1, 15), "r": Decimal("0.05"), "b": Decimal("1.0")},
                {"s": stock_id, "d": date(2026, 3, 1), "r": Decimal("0.20"), "b": Decimal("1.5")},
            ],
        )
    yield stock_id
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM technical_indicators WHERE stock_id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM fundamentals WHERE stock_id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM stocks WHERE id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def test_factor_sees_only_pit_data(admin_engine: Engine, stock: UUID) -> None:
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        ctx = ScoringContext(session, _BEFORE_RESTATE, [stock])
        # Fundamentals: the LATER restatement (pe 12, known T_LATE) is invisible before it is known.
        assert PEFactor().compute(ctx, stock, _BEFORE_RESTATE) == 10.0
        # Indicators: the FUTURE-dated row (0.20) is invisible; the <= as_of row (0.05) is read.
        assert Return6MFactor().compute(ctx, stock, _BEFORE_RESTATE) == pytest.approx(0.05)


def test_restatement_becomes_visible_after_its_knowledge_time(
    admin_engine: Engine, stock: UUID
) -> None:
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        ctx = ScoringContext(session, _AFTER_RESTATE, [stock])
        assert PEFactor().compute(ctx, stock, _AFTER_RESTATE) == 12.0  # correction now known


def test_none_when_stock_has_no_data(admin_engine: Engine, stock: UUID) -> None:
    unknown = uuid4()
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        ctx = ScoringContext(session, _BEFORE_RESTATE, [unknown])
        assert PEFactor().compute(ctx, unknown, _BEFORE_RESTATE) is None
        assert Return6MFactor().compute(ctx, unknown, _BEFORE_RESTATE) is None

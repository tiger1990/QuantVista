"""Bitemporal fundamentals repository (QV-021) — real Postgres, seeded throwaway stock.

Proves point-in-time correctness (03 §5): revisions version (never overwrite), `as_of` reads what
was *known* on a knowledge-date, and the schema invariants (one open version, well-formed interval)
hold. Throwaway market+stock under random ids so nothing touches seeded reference data.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.market_data.fundamentals import (
    fundamentals_as_of,
    record_fundamental_version,
)

pytestmark = pytest.mark.integration

_PERIOD = date(2025, 12, 31)
T0 = datetime(2026, 1, 15, tzinfo=UTC)  # first filing known
T1 = datetime(2026, 1, 20, tzinfo=UTC)  # a no-change re-run
T2 = datetime(2026, 2, 10, tzinfo=UTC)  # restatement known


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
    yield stock_id
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM fundamentals WHERE stock_id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM stocks WHERE id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def _record(
    admin_engine: Engine, stock_id: UUID, ratios: dict[str, Decimal | None], kt: datetime
) -> str:
    with admin_engine.begin() as conn:
        from sqlalchemy.orm import Session

        with Session(bind=conn) as session:
            action = record_fundamental_version(
                session, stock_id, _PERIOD, "quarterly", ratios, knowledge_time=kt
            )
            session.commit()
            return action


def _open_count(admin_engine: Engine, stock_id: UUID) -> int:
    with admin_engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM fundamentals WHERE stock_id = :s AND knowledge_to IS NULL"
                ),
                {"s": stock_id},
            ).scalar_one()
        )


def test_insert_then_unchanged_then_revised(admin_engine: Engine, stock: UUID) -> None:
    assert _record(admin_engine, stock, {"pe": Decimal("10")}, T0) == "inserted"
    assert _record(admin_engine, stock, {"pe": Decimal("10")}, T1) == "unchanged"  # identical
    assert _record(admin_engine, stock, {"pe": Decimal("12")}, T2) == "revised"  # restatement
    assert _open_count(admin_engine, stock) == 1  # exactly one open version (uq_fundamentals_open)
    with admin_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM fundamentals WHERE stock_id = :s"), {"s": stock}
        ).scalar_one()
    assert n == 2  # two versions retained (old closed + new open), nothing destroyed


def test_as_of_reads_what_was_known_then(admin_engine: Engine, stock: UUID) -> None:
    _record(admin_engine, stock, {"pe": Decimal("10")}, T0)
    _record(admin_engine, stock, {"pe": Decimal("12")}, T2)  # revised at T2
    with admin_engine.connect() as conn:
        from sqlalchemy.orm import Session

        with Session(bind=conn) as session:
            before = fundamentals_as_of(session, stock, datetime(2026, 1, 1, tzinfo=UTC))
            mid = fundamentals_as_of(session, stock, T1)  # between T0 and T2
            after = fundamentals_as_of(session, stock, datetime(2026, 3, 1, tzinfo=UTC))
    assert before is None  # nothing was known yet
    assert mid is not None and mid.ratios["pe"] == Decimal("10.000000")  # original
    assert after is not None and after.ratios["pe"] == Decimal("12.000000")  # restated


def test_as_of_selects_latest_period(admin_engine: Engine, stock: UUID) -> None:
    with admin_engine.begin() as conn:
        from sqlalchemy.orm import Session

        with Session(bind=conn) as session:
            record_fundamental_version(
                session,
                stock,
                date(2025, 9, 30),
                "quarterly",
                {"pe": Decimal("9")},
                knowledge_time=T0,
            )
            record_fundamental_version(
                session,
                stock,
                date(2025, 12, 31),
                "quarterly",
                {"pe": Decimal("11")},
                knowledge_time=T0,
            )
            session.commit()
            latest = fundamentals_as_of(session, stock, T1)
    assert latest is not None and latest.period_end == date(2025, 12, 31)


def test_unknown_ratio_column_is_rejected(admin_engine: Engine, stock: UUID) -> None:
    with admin_engine.connect() as conn:
        from sqlalchemy.orm import Session

        with Session(bind=conn) as session, pytest.raises(ValueError, match="bogus"):
            record_fundamental_version(
                session, stock, _PERIOD, "quarterly", {"bogus": Decimal("1")}, knowledge_time=T0
            )


def test_check_rejects_inverted_knowledge_interval(admin_engine: Engine, stock: UUID) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO fundamentals (stock_id, period_end, statement_type, "
                "knowledge_from, knowledge_to) VALUES (:s, :p, 'quarterly', :kf, :kt)"
            ),
            {"s": stock, "p": _PERIOD, "kf": T2, "kt": T0},  # knowledge_to < knowledge_from
        )

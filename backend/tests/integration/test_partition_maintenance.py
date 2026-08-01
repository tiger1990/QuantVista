"""Partition maintenance against a real PostgreSQL (QV-104).

The failure this prevents is silent: with no partition covering a row's date, PostgreSQL routes it
into the `_default` partition instead of erroring. Pruning is lost and the default table grows
unbounded, with nothing in the logs. These tests pin both the maintenance job and a standing guard
that the database is actually ahead of the data.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.core.partitions import (
    ensure_month_partitions,
    parents_missing_cover,
    partition_name,
    partitioned_parents,
)

pytestmark = pytest.mark.integration

# Far enough out that no migration or earlier run has pre-created it. Reached by passing `today`,
# NOT by a huge `months_ahead` — asking for ~55 months of lookahead would create a partition for
# every month in between (hundreds of empty tables) and leave the database littered.
_FUTURE = date(2031, 3, 1)
_FUTURE_NEXT = date(2031, 4, 1)  # `months_ahead=1` also creates the following month


@pytest.fixture
def cleanup_future(admin_engine: Engine) -> Iterator[None]:
    yield
    with admin_engine.begin() as conn:
        for parent in partitioned_parents(Session(bind=conn)):
            for month in (_FUTURE, _FUTURE_NEXT):
                conn.execute(text(f'DROP TABLE IF EXISTS "{partition_name(parent, month)}"'))


def test_discovers_the_partitioned_tables(admin_engine: Engine) -> None:
    """Parents come from the catalog, so a table partitioned later is maintained automatically."""
    with Session(admin_engine) as session:
        parents = partitioned_parents(session)
    # the known monthly-partitioned tables must all be found...
    assert {"daily_prices", "technical_indicators", "scores", "factor_values"} <= set(parents)
    # ...and nothing that is not a partitioned *table* (e.g. partitioned indexes) leaks in
    assert all(not p.startswith("ix_") and not p.endswith("_pkey") for p in parents)


def test_every_partitioned_table_covers_next_month(admin_engine: Engine) -> None:
    """THE GUARD: rows dated next month must have somewhere to go other than `_default`.

    This is the regression that shipped — migrations create only the current and next month, so a
    database migrated more than a month ago silently loses pruning. It fails loudly here instead.
    """
    with Session(admin_engine) as session:
        missing = parents_missing_cover(session, date.today() + timedelta(days=31))
    assert missing == [], (
        "these partitioned tables have no partition for next month, so their rows will fall into "
        f"the _default partition with no error: {missing}"
    )


def test_ensure_creates_missing_future_partitions(
    admin_engine: Engine, cleanup_future: None
) -> None:
    with Session(admin_engine) as session:
        assert parents_missing_cover(session, _FUTURE), "fixture date should start uncovered"

        result = ensure_month_partitions(session, today=_FUTURE, months_ahead=1)
        session.commit()

        assert parents_missing_cover(session, _FUTURE) == []
        assert result.months == (_FUTURE, _FUTURE_NEXT)  # exactly the months asked for, no sprawl
        assert result.ensured == len(result.parents) * 2


def test_ensure_is_idempotent(admin_engine: Engine, cleanup_future: None) -> None:
    """A daily schedule means this runs constantly; re-running must be a harmless no-op."""
    with Session(admin_engine) as session:
        ensure_month_partitions(session, today=_FUTURE, months_ahead=1)
        session.commit()
        ensure_month_partitions(session, today=_FUTURE, months_ahead=1)  # must not raise
        session.commit()
        assert parents_missing_cover(session, _FUTURE) == []


def test_row_lands_in_a_real_partition_not_default(
    admin_engine: Engine, cleanup_future: None
) -> None:
    """End-to-end proof: the same insert that fell to `_default` now routes to a month partition."""
    with Session(admin_engine) as session:
        ensure_month_partitions(session, today=_FUTURE, months_ahead=1)
        session.commit()

    with admin_engine.begin() as conn:
        stock_id = conn.execute(text("SELECT id FROM stocks LIMIT 1")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO daily_prices (stock_id, date, close, adj_close, source) "
                "VALUES (:s, :d, 1, 1, 'qv104-probe')"
            ),
            {"s": stock_id, "d": _FUTURE},
        )
        landed = conn.execute(
            text("SELECT tableoid::regclass::text FROM daily_prices WHERE source = 'qv104-probe'")
        ).scalar_one()
        conn.execute(text("DELETE FROM daily_prices WHERE source = 'qv104-probe'"))

    assert landed == partition_name("daily_prices", _FUTURE)
    assert not landed.endswith("_default")

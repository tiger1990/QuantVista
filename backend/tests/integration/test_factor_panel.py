"""The factor panel read that feeds the ML feature store (QV-087) — real PostgreSQL.

Unit tests cover the engineering; this covers the seam to the database: that a range read returns
what the pipeline expects, in the order it relies on, without disturbing the single-date read the
scoring path depends on.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.repositories import factor_values_for, factor_values_panel
from quantvista.ml.features import build_features

pytestmark = pytest.mark.integration

_START = date(2026, 2, 2)
_DAYS = 5
_FACTORS = ("pe", "roe", "ret_6m")


@pytest.fixture
def seeded_factors(admin_engine: Engine) -> Iterator[list[UUID]]:
    """Two stocks with a small factor panel — seeded, not borrowed from ambient dev data."""
    market_id, stock_ids = uuid4(), [uuid4(), uuid4()]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'FP', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"FP{uuid4().hex[:5]}"},
        )
        for i, sid in enumerate(stock_ids):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name) "
                    "VALUES (:id, :m, :sym, 'Co')"
                ),
                {"id": sid, "m": market_id, "sym": f"FP{i}{uuid4().hex[:4]}"},
            )
        conn.execute(
            text(
                "INSERT INTO factor_values "
                "(stock_id, date, factor_key, raw_value, zscore, percentile_sector, "
                " percentile_universe) VALUES (:s, :d, :k, :raw, :z, :ps, :pu)"
            ),
            [
                {
                    "s": sid,
                    "d": _START + timedelta(days=n),
                    "k": key,
                    "raw": 10 + n,
                    "z": float(n - 2 + i),
                    "ps": 50 + n,
                    "pu": 40 + n,
                }
                for i, sid in enumerate(stock_ids)
                for n in range(_DAYS)
                for key in _FACTORS
            ],
        )
    yield stock_ids
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM factor_values WHERE stock_id = ANY(:ids)"), {"ids": stock_ids}
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:ids)"), {"ids": stock_ids})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def test_panel_returns_the_whole_range(admin_engine: Engine, seeded_factors: list[UUID]) -> None:
    with Session(admin_engine) as session:
        rows = factor_values_panel(
            session, seeded_factors, _START, _START + timedelta(days=_DAYS - 1)
        )
    assert len(rows) == len(seeded_factors) * _DAYS * len(_FACTORS)
    assert {r["date"] for r in rows} == {_START + timedelta(days=n) for n in range(_DAYS)}


def test_panel_is_ordered_for_time_series_transforms(
    admin_engine: Engine, seeded_factors: list[UUID]
) -> None:
    """The feature pipeline lags and rolls per stock over date; unordered input would corrupt it."""
    with Session(admin_engine) as session:
        rows = factor_values_panel(
            session, seeded_factors, _START, _START + timedelta(days=_DAYS - 1)
        )
    keyed = [(str(r["stock_id"]), r["date"], str(r["factor_key"])) for r in rows]
    assert keyed == sorted(keyed)


def test_panel_respects_the_range_bounds(admin_engine: Engine, seeded_factors: list[UUID]) -> None:
    with Session(admin_engine) as session:
        rows = factor_values_panel(session, seeded_factors, _START, _START + timedelta(days=1))
    assert {r["date"] for r in rows} == {_START, _START + timedelta(days=1)}


def test_empty_stock_list_short_circuits(admin_engine: Engine) -> None:
    with Session(admin_engine) as session:
        assert factor_values_panel(session, [], _START, _START) == []


def test_single_date_read_is_unchanged(admin_engine: Engine, seeded_factors: list[UUID]) -> None:
    """The scoring path depends on `factor_values_for`; the panel must not have disturbed it."""
    with Session(admin_engine) as session:
        by_stock = factor_values_for(session, seeded_factors, _START)
    assert set(by_stock) == set(seeded_factors)
    assert {fv.factor_key for fv in by_stock[seeded_factors[0]]} == set(_FACTORS)


def test_panel_feeds_the_feature_pipeline_end_to_end(
    admin_engine: Engine, seeded_factors: list[UUID]
) -> None:
    """The seam that matters: database rows in, engineered frame out."""
    with Session(admin_engine) as session:
        rows = factor_values_panel(
            session, seeded_factors, _START, _START + timedelta(days=_DAYS - 1)
        )
    frame = build_features(rows, list(_FACTORS))

    assert frame.height == len(seeded_factors) * _DAYS
    assert "pe__zscore" in frame.columns and "pe__zscore__delta21" in frame.columns
    assert frame["pe__zscore"].null_count() == 0

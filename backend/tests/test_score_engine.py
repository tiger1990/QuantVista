"""ScoreEngine unit tests (QV-029) — category blend + the decomposition==composite invariant.

Fake factors (ignore ctx, return preset raws) + a patched sector lookup → compute_universe runs
without a DB. Pins: weighted re-normalized composite, decomposition sums to composite exactly,
missing-factor exclusion + coverage, and sentiment → NULL (no factor).
"""

from __future__ import annotations

from datetime import date
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from quantvista.analytics import scoring
from quantvista.analytics.factors import Factor, FactorCategory
from quantvista.analytics.normalizer import Normalizer
from quantvista.analytics.scoring import DEFAULT_WEIGHTS, ScoreEngine, compute_universe

A, B, C = uuid4(), uuid4(), uuid4()
_AS_OF = date(2026, 1, 20)


class _FakeFactor(Factor):
    def __init__(
        self, key: str, category: FactorCategory, direction: int, values: dict[UUID, float | None]
    ) -> None:
        self.key = key  # type: ignore[misc]
        self.category = category  # type: ignore[misc]
        self.direction = direction  # type: ignore[misc]
        self._values = values

    def compute(self, ctx: object, stock_id: UUID, as_of: date) -> float | None:
        return self._values.get(stock_id)


def test_blend_decomposition_sums_to_composite() -> None:
    sub = {
        FactorCategory.FUNDAMENTAL: 80.0,
        FactorCategory.MOMENTUM: 60.0,
        FactorCategory.RISK: 40.0,
    }
    composite, decomp = ScoreEngine()._blend(sub)
    assert composite == pytest.approx(sum(decomp.values()))  # THE invariant
    # weights .40/.20/.10 (total .70) re-normalized: 4/7, 2/7, 1/7
    assert composite == pytest.approx(80 * 4 / 7 + 60 * 2 / 7 + 40 * 1 / 7)
    assert set(decomp) == {"fundamental", "momentum", "risk"}  # quality/sentiment absent


def test_blend_empty_is_zero() -> None:
    assert ScoreEngine()._blend({}) == (0.0, {})


def test_compute_universe_aggregates_decomposes_and_covers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scoring, "stock_sectors", lambda s, ids: {A: "X", B: "X", C: "X"})
    factors = [
        _FakeFactor("pe", FactorCategory.FUNDAMENTAL, -1, {A: 10.0, B: 20.0, C: None}),
        _FakeFactor("roe", FactorCategory.QUALITY, 1, {A: 0.20, B: 0.10, C: 0.15}),
        _FakeFactor("ret_6m", FactorCategory.MOMENTUM, 1, {A: 0.05, B: 0.10, C: 0.08}),
    ]
    # session unused: fake factors ignore ctx, stock_sectors is patched.
    scores = compute_universe(
        cast(Session, None),
        [A, B, C],
        _AS_OF,
        factors=factors,
        normalizer=Normalizer(),
        weights=DEFAULT_WEIGHTS,
    )
    by = {s.stock_id: s for s in scores}
    assert set(by) == {A, B, C}
    for s in scores:
        assert s.composite == pytest.approx(sum(s.decomposition.values()))  # invariant per stock
        assert 0.0 <= s.composite <= 100.0
        assert s.sentiment is None and s.risk is None  # no sentiment/risk factor supplied
        assert (s.weights_version, s.model_version) == ("v1", "score-v1")
    assert by[C].fundamental is None  # C's pe was None → category excluded
    assert by[C].coverage == pytest.approx(2 / 3 * 100)  # 2 of 3 factors
    assert by[A].coverage == 100.0

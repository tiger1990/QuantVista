"""Normalizer unit tests (QV-029) — sector z-score → percentile, direction-adjusted.

Crafted tiny universe with known z/percentiles; pins the winsorize→sector-z→percentile pipeline,
direction flip, σ=0 / singleton neutrality, and None/non-finite exclusion. Pure (no DB).
"""

from __future__ import annotations

import math
from uuid import UUID, uuid4

import pytest

from quantvista.analytics.normalizer import Normalizer

S1, S2, S3, S4 = uuid4(), uuid4(), uuid4(), uuid4()


def test_sector_zscore_and_percentiles() -> None:
    values = {S1: 10.0, S2: 20.0, S3: 30.0, S4: float("nan")}  # S4 non-finite → excluded
    sectors = {S1: "A", S2: "A", S3: "B", S4: "B"}
    out = Normalizer().normalize(values, sectors, direction=1)

    assert set(out) == {S1, S2, S3}  # NaN dropped
    # Sector A (10, 20): mean 15, sample std sqrt(50) ≈ 7.071 → z ∓0.707.
    assert out[S1].zscore == pytest.approx(-0.7071, abs=1e-3)
    assert out[S2].zscore == pytest.approx(0.7071, abs=1e-3)
    assert out[S3].zscore == 0.0  # sector B singleton → neutral
    # within-sector percentile (n=2 → 0 / 100); singleton → 50
    assert (out[S1].percentile_sector, out[S2].percentile_sector) == (0.0, 100.0)
    assert out[S3].percentile_sector == 50.0
    # universe percentile of the sector-z: order S1(-0.71) < S3(0) < S2(0.71)
    assert (
        out[S1].percentile_universe,
        out[S3].percentile_universe,
        out[S2].percentile_universe,
    ) == (
        0.0,
        50.0,
        100.0,
    )


def test_direction_minus_one_flips_ranking() -> None:
    values = {S1: 10.0, S2: 20.0}
    sectors = {S1: "A", S2: "A"}
    up = Normalizer().normalize(values, sectors, direction=1)
    down = Normalizer().normalize(values, sectors, direction=-1)
    # +1: higher value better → S2 top. -1 (e.g. PE/beta): lower value better → S1 top.
    assert up[S2].percentile_universe > up[S1].percentile_universe
    assert down[S1].percentile_universe > down[S2].percentile_universe


def test_zero_variance_sector_is_neutral() -> None:
    values = {S1: 5.0, S2: 5.0, S3: 5.0}
    sectors = {S1: "A", S2: "A", S3: "A"}
    out = Normalizer().normalize(values, sectors, direction=1)
    assert all(r.zscore == 0.0 for r in out.values())  # σ=0 → all neutral


def test_none_values_excluded() -> None:
    values: dict[UUID, float | None] = {S1: 10.0, S2: None, S3: math.inf}
    sectors = {S1: "A", S2: "A", S3: "A"}
    out = Normalizer().normalize(values, sectors, direction=1)
    assert set(out) == {S1}  # None + inf dropped


def test_empty_input() -> None:
    assert Normalizer().normalize({}, {}, direction=1) == {}

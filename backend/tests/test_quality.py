"""Unit tests for the data-quality gate evaluator (market_data.quality, QV-018).

Pure math: given a PriceQualityMetrics snapshot + thresholds, evaluate_quality decides pass/fail
and which gates tripped. No DB, no yfinance.
"""

from __future__ import annotations

from quantvista.market_data.quality import (
    PriceQualityMetrics,
    QualityThresholds,
    evaluate_quality,
)


def _metrics(**overrides: object) -> PriceQualityMetrics:
    """A clean, all-gates-pass baseline; override one field to trip a single gate."""
    base: dict[str, object] = {
        "expected_stocks": 100,
        "stocks_with_data": 100,
        "ohlcv_null_cells": 0,
        "ohlcv_total_cells": 500,
        "nonpositive_price_rows": 0,
        "ohlc_bound_violation_rows": 0,
        "expected_sessions": 1,
        "observed_slots": 100,
        "missing_symbols_sample": [],
    }
    base.update(overrides)
    return PriceQualityMetrics(**base)  # type: ignore[arg-type]


def _gates(metrics: PriceQualityMetrics) -> set[str]:
    return {v.gate for v in evaluate_quality(metrics, QualityThresholds()).violations}


def test_clean_metrics_pass_all_gates() -> None:
    report = evaluate_quality(_metrics(), QualityThresholds())
    assert report.passed
    assert report.violations == []


def test_g1_coverage_trips_when_stocks_missing() -> None:
    # 90/100 = 0.90 < 0.95
    report = evaluate_quality(
        _metrics(stocks_with_data=90, missing_symbols_sample=["AAA", "BBB"]), QualityThresholds()
    )
    assert not report.passed
    assert _gates(_metrics(stocks_with_data=90)) == {"coverage"}


def test_g2_null_rate_trips() -> None:
    # 10/500 = 0.02 > 0.01
    assert _gates(_metrics(ohlcv_null_cells=10)) == {"null_rate"}


def test_g3_price_sanity_trips_on_nonpositive_or_bound_violation() -> None:
    assert _gates(_metrics(nonpositive_price_rows=1)) == {"price_sanity"}
    assert _gates(_metrics(ohlc_bound_violation_rows=3)) == {"price_sanity"}


def test_g4_gap_trips_over_a_window() -> None:
    # 100 stocks x 10 sessions = 1000 grid; 30 missing → 0.03 > 0.02. Coverage still 100/100.
    assert _gates(_metrics(expected_sessions=10, observed_slots=970)) == {"gap"}


def test_boundary_values_exactly_at_threshold_pass() -> None:
    assert evaluate_quality(_metrics(stocks_with_data=95), QualityThresholds()).passed  # 0.95
    assert evaluate_quality(_metrics(ohlcv_null_cells=5), QualityThresholds()).passed  # 0.01
    # 20/1000 = 0.02 exactly
    assert evaluate_quality(
        _metrics(expected_sessions=10, observed_slots=980), QualityThresholds()
    ).passed


def test_empty_universe_passes_without_division_error() -> None:
    empty = _metrics(expected_stocks=0, stocks_with_data=0, ohlcv_total_cells=0, observed_slots=0)
    report = evaluate_quality(empty, QualityThresholds())
    assert report.passed and report.violations == []


def test_multiple_gates_can_trip_together() -> None:
    gates = _gates(_metrics(stocks_with_data=50, nonpositive_price_rows=2))
    assert gates == {"coverage", "price_sanity"}

"""Data-quality gate evaluator (QV-018) — pure, no DB, no yfinance.

Given a snapshot of aggregate metrics over a run's ``daily_prices`` (gathered by the repository)
and a set of thresholds, decide whether the ingest is fit for downstream compute. Four gates
(``06`` §5): coverage vs the expected universe, OHLCV null-rate, price sanity (no ``<= 0`` and no
OHLC-bound violation), and gap/continuity vs the trading calendar. ``adj_close`` is intentionally
excluded — it is (re)computed asynchronously by the corporate-action job and may lag a fresh ingest.

This module is a DAG leaf: it takes DTOs and returns a report; the service/job wire it to the DB
and event bus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

# Gate defaults (``06`` §5). Overridable per call for wide backfills / tests.
_DEFAULT_MIN_COVERAGE = Decimal("0.95")
_DEFAULT_MAX_NULL_RATE = Decimal("0.01")
_DEFAULT_MAX_MISSING_SESSION_RATE = Decimal("0.02")


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    min_coverage: Decimal = _DEFAULT_MIN_COVERAGE
    max_null_rate: Decimal = _DEFAULT_MAX_NULL_RATE
    max_missing_session_rate: Decimal = _DEFAULT_MAX_MISSING_SESSION_RATE


@dataclass(frozen=True, slots=True)
class PriceQualityMetrics:
    """Aggregates over ``daily_prices`` for a universe + date window (from the repository)."""

    expected_stocks: int  # size of the active universe
    stocks_with_data: int  # distinct stocks with >=1 row in the window
    ohlcv_null_cells: int  # NULLs across open/high/low/close/volume
    ohlcv_total_cells: int  # rows * 5
    nonpositive_price_rows: int  # rows with open/high/low/close <= 0
    ohlc_bound_violation_rows: int  # rows breaking high>=low, high>=open/close, low<=open/close
    expected_sessions: int  # len(sessions_in_range(start, end))
    observed_slots: int  # count of (stock, date) rows present in the window
    missing_symbols_sample: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GateViolation:
    gate: str
    observed: str
    threshold: str
    detail: str


@dataclass(frozen=True, slots=True)
class QualityReport:
    passed: bool
    violations: list[GateViolation]


def evaluate_quality(metrics: PriceQualityMetrics, thresholds: QualityThresholds) -> QualityReport:
    """Run the four gates. ``passed`` iff no gate is violated."""
    violations: list[GateViolation] = []

    # G1 — coverage: enough of the universe actually landed?
    if metrics.expected_stocks > 0:
        coverage = Decimal(metrics.stocks_with_data) / Decimal(metrics.expected_stocks)
        if coverage < thresholds.min_coverage:
            missing = metrics.expected_stocks - metrics.stocks_with_data
            sample = ", ".join(metrics.missing_symbols_sample)
            violations.append(
                GateViolation(
                    "coverage",
                    f"{coverage:.4f}",
                    f"{thresholds.min_coverage}",
                    f"{missing} of {metrics.expected_stocks} stocks missing"
                    + (f" (e.g. {sample})" if sample else ""),
                )
            )

    # G2 — null-rate over OHLCV cells.
    if metrics.ohlcv_total_cells > 0:
        null_rate = Decimal(metrics.ohlcv_null_cells) / Decimal(metrics.ohlcv_total_cells)
        if null_rate > thresholds.max_null_rate:
            violations.append(
                GateViolation(
                    "null_rate",
                    f"{null_rate:.4f}",
                    f"{thresholds.max_null_rate}",
                    f"{metrics.ohlcv_null_cells} null cells of {metrics.ohlcv_total_cells}",
                )
            )

    # G3 — price sanity: zero tolerance for <=0 prices or OHLC-bound violations.
    bad_rows = metrics.nonpositive_price_rows + metrics.ohlc_bound_violation_rows
    if bad_rows > 0:
        violations.append(
            GateViolation(
                "price_sanity",
                f"{bad_rows}",
                "0",
                f"{metrics.nonpositive_price_rows} non-positive, "
                f"{metrics.ohlc_bound_violation_rows} OHLC-bound violations",
            )
        )

    # G4 — gap/continuity: how much of the (stock x session) grid is missing?
    grid = metrics.expected_stocks * metrics.expected_sessions
    if grid > 0:
        missing_slots = grid - metrics.observed_slots
        missing_rate = Decimal(missing_slots) / Decimal(grid)
        if missing_rate > thresholds.max_missing_session_rate:
            violations.append(
                GateViolation(
                    "gap",
                    f"{missing_rate:.4f}",
                    f"{thresholds.max_missing_session_rate}",
                    f"{missing_slots} missing of {grid} (stock x session) slots",
                )
            )

    return QualityReport(passed=not violations, violations=violations)

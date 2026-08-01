"""Feature store correctness (QV-087) — no DB.

Two of these matter more than the rest. The **leakage** test is the epic's foundation: every ML
claim downstream (walk-forward CV, the champion/challenger gate) is worthless if a feature can see
the future. The **parity** test pins `05` §5's central promise — that training and serving features
are identical — as a property of the code rather than of discipline.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import cast

import polars as pl
import pytest

from quantvista.analytics.factors import ALL_FACTORS
from quantvista.ml.features import (
    LAG_WINDOWS,
    build_features,
    feature_names,
    feature_specs,
    serve_features,
)

_KEYS = [f.key for f in ALL_FACTORS]
_D0 = date(2026, 1, 1)
_STOCKS = ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")


def _panel(
    n_days: int = 90,
    *,
    zscore_of: Callable[[int, int], float] = lambda i, s: float((i % 7) - 3 + s),
    keys: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    """A long factor panel: ``n_days`` sessions per stock, every factor present."""
    keys = list(keys) if keys is not None else _KEYS
    return [
        {
            "stock_id": sid,
            "date": _D0 + timedelta(days=i),
            "factor_key": k,
            "raw_value": 1.0 + i * 0.1 + s,
            "zscore": float(zscore_of(i, s)),
            "percentile_sector": 50.0 + (i % 40),
            "percentile_universe": 40.0 + (i % 50),
        }
        for s, sid in enumerate(_STOCKS)
        for i in range(n_days)
        for k in keys
    ]


def test_produces_more_than_a_hundred_features() -> None:
    """The AC says 100+; assert it so the number is enforced rather than aspirational."""
    names = feature_names(_KEYS)
    assert len(names) >= 100, f"only {len(names)} features"
    assert len(set(names)) == len(names), "feature names must be unique"


def test_frame_columns_match_the_catalog_exactly() -> None:
    frame = build_features(_panel(), _KEYS)
    expected = ["stock_id", "date", *feature_names(_KEYS)]
    assert frame.columns == expected


def test_no_feature_can_see_the_future() -> None:
    """THE GUARD: change only the LAST date; nothing on earlier dates may move.

    Constructed as a counterfactual rather than an inspection — a rolling window that included the
    current-and-future rows, or a backward fill, would shift earlier values and fail here.
    """
    base = _panel(n_days=80)
    tampered = [
        {**row, "zscore": float(cast(float, row["zscore"])) + 100.0}
        if row["date"] == _D0 + timedelta(days=79)
        else row
        for row in base
    ]

    before = build_features(base, _KEYS).filter(pl.col("date") < _D0 + timedelta(days=79))
    after = build_features(tampered, _KEYS).filter(pl.col("date") < _D0 + timedelta(days=79))

    assert before.equals(after), "a future value changed a past feature — look-ahead leaked in"


def test_lag_is_the_value_from_that_many_sessions_earlier() -> None:
    """Pins the direction of `shift`: a lag must reach backwards, never forwards."""
    rows = _panel(n_days=60, zscore_of=lambda i, s: float(i), keys=["pe"])
    frame = build_features(rows, ["pe"]).filter(pl.col("stock_id") == _STOCKS[0]).sort("date")
    w = LAG_WINDOWS[0]
    lagged = frame[f"pe__zscore__lag{w}"].to_list()
    current = frame["pe__zscore"].to_list()

    assert lagged[:w] == [None] * w, "no history yet → null, never a peek forward"
    assert lagged[w:] == current[:-w], f"lag{w} must equal the value {w} rows earlier"


def test_delta_is_current_minus_past_not_the_reverse() -> None:
    rows = _panel(n_days=60, zscore_of=lambda i, s: float(i), keys=["pe"])
    frame = build_features(rows, ["pe"]).filter(pl.col("stock_id") == _STOCKS[0]).sort("date")
    w = LAG_WINDOWS[0]
    deltas = [d for d in frame[f"pe__zscore__delta{w}"].to_list() if d is not None]
    assert deltas and all(d == pytest.approx(float(w)) for d in deltas), (
        "a +1/session series must give delta == window; a sign flip means past-minus-current"
    )


def test_serving_a_date_equals_that_date_in_the_training_panel() -> None:
    """`05` §5's central claim: no train/serve skew. Structural, not documented."""
    rows = _panel(n_days=75)
    as_of = _D0 + timedelta(days=74)

    panel_row = build_features(rows, _KEYS).filter(pl.col("date") == as_of).sort("stock_id")
    served = serve_features(rows, _KEYS, as_of=as_of).sort("stock_id")

    assert served.equals(panel_row), "serving diverged from training for the same date"


def test_features_are_per_stock_not_mixed_across_the_universe() -> None:
    """A window that forgot `over('stock_id')` would blend one stock's history into another."""
    rows = _panel(n_days=60, zscore_of=lambda i, s: float(i + 1000 * s), keys=["pe"])
    frame = build_features(rows, ["pe"]).sort(["stock_id", "date"])
    w = LAG_WINDOWS[0]
    for sid in _STOCKS:
        one = frame.filter(pl.col("stock_id") == sid)
        assert one[f"pe__zscore__lag{w}"].to_list()[:w] == [None] * w, (
            "each stock's history must start fresh; leading nulls prove no bleed from the previous"
        )


def test_a_missing_factor_yields_nulls_not_zeros() -> None:
    """A stock with no sentiment must not look like a stock with neutral sentiment."""
    rows = [
        r
        for r in _panel(n_days=40)
        if not (r["factor_key"] == "sentiment" and r["stock_id"] == _STOCKS[1])
    ]
    frame = build_features(rows, _KEYS)
    missing = frame.filter(pl.col("stock_id") == _STOCKS[1])["sentiment__zscore"].to_list()
    assert all(v is None for v in missing), "absent coverage was imputed — that biases the model"


def test_empty_panel_is_handled() -> None:
    assert build_features([], _KEYS).is_empty()


def test_every_spec_describes_itself() -> None:
    for spec in feature_specs(_KEYS):
        assert spec.description.strip(), f"{spec.name} has no description"
        assert spec.source_factor in _KEYS
        assert (spec.window is None) == (spec.family == "base")

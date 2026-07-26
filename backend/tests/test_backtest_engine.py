"""Unit test for the BacktestEngine seam (QV-062) — placeholder contract until QV-065."""

from __future__ import annotations

from quantvista.analytics.backtest import BacktestEngine, BacktestResult
from quantvista.schemas.backtest import BacktestSpec

_SPEC = BacktestSpec.model_validate(
    {
        "rules": {"top_n": 20},
        "start": "2020-01-01",
        "end": "2020-06-30",
    }
)


def test_placeholder_engine_returns_empty_valid_result() -> None:
    result = BacktestEngine().run(_SPEC)
    assert isinstance(result, BacktestResult)
    assert result.metrics == {}
    assert result.result_ref is None

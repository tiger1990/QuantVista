"""Unit tests for the backtest reproducibility fingerprint (QV-069) — pure, no DB.

``_reproducibility_hash`` sha256s the canonical spec + methodology versions: identical for the same
recipe, different for any spec-field or version change. Deterministic + fast.
"""

from __future__ import annotations

import pytest

from quantvista.analytics import backtest as engine
from quantvista.analytics.backtest import _reproducibility_hash
from quantvista.schemas.backtest import BacktestSpec

_BASE = {
    "type": "factor_strategy",
    "universe": "NIFTY200",
    "rules": {"rank_by": "composite", "top_n": 20, "rebalance": "monthly"},
    "start": "2020-01-01",
    "end": "2020-12-31",
    "costs_bps": 15,
    "benchmark": "NIFTY200_TRI",
}


def _spec(**over: object) -> BacktestSpec:
    return BacktestSpec.model_validate({**_BASE, **over})


def test_is_a_hex_sha256() -> None:
    h = _reproducibility_hash(_spec())
    assert isinstance(h, str) and len(h) == 64
    int(h, 16)  # hex-decodable


def test_same_spec_same_hash() -> None:
    assert _reproducibility_hash(_spec()) == _reproducibility_hash(_spec())


def test_canonicalisation_ignores_key_order() -> None:
    # Two dicts with different key order validate to the same model → same hash.
    reordered = {
        "benchmark": "NIFTY200_TRI",
        "end": "2020-12-31",
        "costs_bps": 15,
        "start": "2020-01-01",
        "rules": {"rebalance": "monthly", "top_n": 20, "rank_by": "composite"},
        "universe": "NIFTY200",
        "type": "factor_strategy",
    }
    assert _reproducibility_hash(_spec()) == _reproducibility_hash(
        BacktestSpec.model_validate(reordered)
    )


@pytest.mark.parametrize(
    "over",
    [
        {"rules": {"rank_by": "momentum", "top_n": 20, "rebalance": "monthly"}},
        {"rules": {"rank_by": "composite", "top_n": 21, "rebalance": "monthly"}},
        {"rules": {"rank_by": "composite", "top_n": 20, "rebalance": "quarterly"}},
        {"costs_bps": 16},
        {"start": "2019-01-01"},
        {"end": "2021-12-31"},
    ],
)
def test_any_spec_change_changes_hash(over: dict[str, object]) -> None:
    assert _reproducibility_hash(_spec()) != _reproducibility_hash(_spec(**over))


def test_methodology_version_bump_changes_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    before = _reproducibility_hash(_spec())
    monkeypatch.setattr(engine, "MODEL_VERSION", "score-v2")
    assert _reproducibility_hash(_spec()) != before

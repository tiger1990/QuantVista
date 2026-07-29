"""Reproducibility guarantee (QV-069) — real Postgres, real engine.

Runs the *whole* ``BacktestEngine`` through the real ``BacktestDataAccess`` twice with the **same
spec** and asserts the two ``metrics`` dicts are byte-identical (every metric + the
``reproducibility_hash`` + versions). Any determinism regression — a stochastic step, unordered
iteration, or a floating-point path change — makes the two runs diverge and trips this guard.

Read-only (no seed/writes): whatever NIFTY200 data exists, two runs on the same session are
identical — so the guard is robust to data state (populated dev DB or a freshly-seeded CI DB).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from quantvista.analytics.backtest import BacktestEngine
from quantvista.analytics.backtest_data import BacktestDataAccess
from quantvista.schemas.backtest import BacktestSpec

pytestmark = pytest.mark.integration

_SPEC = BacktestSpec.model_validate(
    {
        "type": "factor_strategy",
        "universe": "NIFTY200",
        "rules": {"rank_by": "composite", "top_n": 10, "rebalance": "monthly"},
        "start": "2026-05-01",
        "end": "2026-06-30",
        "costs_bps": 15,
    }
)


@pytest.fixture
def session(admin_engine: Engine) -> Iterator[Session]:
    with admin_engine.connect() as conn, Session(bind=conn) as s:
        yield s


def test_same_spec_reproduces_metrics(session: Session) -> None:
    m1 = BacktestEngine(BacktestDataAccess(session)).run(_SPEC).metrics
    m2 = BacktestEngine(BacktestDataAccess(session)).run(_SPEC).metrics
    assert m1 == m2  # byte-identical → deterministic
    assert {"reproducibility_hash", "model_version", "weights_version"} <= set(m1)


def test_reproducibility_hash_is_recipe_specific(session: Session) -> None:
    base = BacktestEngine(BacktestDataAccess(session)).run(_SPEC).metrics["reproducibility_hash"]
    other = _SPEC.model_copy(update={"end": date(2026, 6, 15)})
    changed = BacktestEngine(BacktestDataAccess(session)).run(other).metrics["reproducibility_hash"]
    assert base != changed  # a different spec → a different fingerprint

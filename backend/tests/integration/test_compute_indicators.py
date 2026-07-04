"""compute_indicators over real Postgres (QV-025) — seeded 260-session price history.

Proves the Polars job writes one indicators row per stock with sane values, is idempotent, and emits
IndicatorsComputed. Throwaway universe under a unique index_code; cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.core.events import get_event_bus, reset_event_bus
from quantvista.jobs.compute import _run_compute
from quantvista.jobs.framework import run_key

pytestmark = pytest.mark.integration

_N = 260  # ≥ 252 so every indicator (incl. ret_12m / beta_1y) computes
_START = date(2025, 1, 1)
_TARGET = _START + timedelta(days=_N - 1)


@dataclass
class _Env:
    market: str
    index_code: str
    ids: list[UUID]


@pytest.fixture(autouse=True)
def _reset_bus() -> Iterator[None]:
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.fixture
def universe(admin_engine: Engine) -> Iterator[_Env]:
    market_id, index_code = uuid4(), f"TESTIND_{uuid4().hex[:8]}"
    aaa, bbb = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'T', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        prices = []
        for sid, base in [(aaa, 100.0), (bbb, 50.0)]:
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name) "
                    "VALUES (:id, :m, :s, 'Co')"
                ),
                {"id": sid, "m": market_id, "s": f"S{uuid4().hex[:5]}"},
            )
            conn.execute(
                text(
                    "INSERT INTO index_constituents (id, index_code, stock_id, effective_from) "
                    "VALUES (gen_random_uuid(), :ic, :s, '2020-01-01')"
                ),
                {"ic": index_code, "s": sid},
            )
            for i in range(_N):
                p = base + 0.1 * i  # gentle upward ramp
                prices.append(
                    {
                        "s": sid,
                        "d": _START + timedelta(days=i),
                        "c": Decimal(str(round(p, 4))),
                        "h": Decimal(str(round(p * 1.01, 4))),
                        "l": Decimal(str(round(p * 0.99, 4))),
                    }
                )
        conn.execute(
            text(
                "INSERT INTO daily_prices "
                "(stock_id, date, close, adj_close, high, low, volume, source) "
                "VALUES (:s, :d, :c, :c, :h, :l, 1000, 'seed')"
            ),
            prices,
        )
        market = str(
            conn.execute(
                text("SELECT code FROM markets WHERE id=:m"), {"m": market_id}
            ).scalar_one()
        )
    yield _Env(market, index_code, [aaa, bbb])
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM technical_indicators WHERE stock_id = ANY(:i)"), {"i": [aaa, bbb]}
        )
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:i)"), {"i": [aaa, bbb]})
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code=:ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": [aaa, bbb]})
        conn.execute(text("DELETE FROM markets WHERE id=:m"), {"m": market_id})
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "ind:%"})


def _ti_count(admin_engine: Engine, ids: list[UUID]) -> int:
    with admin_engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM technical_indicators WHERE stock_id = ANY(:i)"),
                {"i": ids},
            ).scalar_one()
        )


def test_compute_writes_a_row_per_stock_with_sane_values(
    admin_engine: Engine, universe: _Env
) -> None:
    events: list[dict[str, object]] = []
    get_event_bus().subscribe("IndicatorsComputed", lambda env: events.append(env))

    key = run_key("ind", "T", uuid4().hex[:8])
    outcome = _run_compute(universe.market, _TARGET, key, universe.index_code)

    assert outcome.status.value == "succeeded"
    with admin_engine.connect() as conn:  # run_job recorded the execution in jobs_runs
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"), {"k": key}
        ).scalar_one()
    assert status == "succeeded"
    assert _ti_count(admin_engine, universe.ids) == 2
    assert events
    payload = events[0]["payload"]
    assert isinstance(payload, dict) and payload["stocks"] == 2
    with admin_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT sma_50, sma_200, rsi_14, ret_12m, beta_1y FROM technical_indicators "
                "WHERE stock_id = :s AND date = :d"
            ),
            {"s": universe.ids[0], "d": _TARGET},
        ).one()
    assert row.sma_50 is not None and row.sma_200 is not None  # 260 sessions → both present
    assert row.rsi_14 == Decimal("100.0000")  # strictly rising ramp
    assert row.ret_12m is not None and row.beta_1y is not None


def test_compute_is_idempotent(admin_engine: Engine, universe: _Env) -> None:
    for _ in range(2):
        _run_compute(universe.market, _TARGET, run_key("ind", "T", "same"), universe.index_code)
    assert _ti_count(admin_engine, universe.ids) == 2  # re-run overwrites, no duplicate rows

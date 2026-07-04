"""Producer → shared bus → subscriber, end-to-end (QV-024).

Proves the wiring: a real producer (DataQualityService) built with get_event_bus() publishes, and a
handler subscribed on the SAME shared bus receives the envelope. Default backend is in_process.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.core.events import get_event_bus, reset_event_bus
from quantvista.market_data.services import DataQualityService

pytestmark = pytest.mark.integration

_D = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def _reset_bus() -> Iterator[None]:
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.fixture
def seeded(admin_engine: Engine) -> Iterator[tuple[str, str, UUID]]:
    market_id, index_code, stock_id = uuid4(), f"TESTEB_{uuid4().hex[:8]}", uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'T', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        conn.execute(
            text(
                "INSERT INTO stocks (id, market_id, symbol, company_name) "
                "VALUES (:id, :m, 'AAA', 'Co')"
            ),
            {"id": stock_id, "m": market_id},
        )
        conn.execute(
            text(
                "INSERT INTO index_constituents (id, index_code, stock_id, effective_from) "
                "VALUES (gen_random_uuid(), :ic, :s, '2020-01-01')"
            ),
            {"ic": index_code, "s": stock_id},
        )
        conn.execute(
            text(
                "INSERT INTO daily_prices "
                "(stock_id, date, open, high, low, close, adj_close, volume, source) "
                "VALUES (:s, :d, 100, 105, 99, 102, 102, 1000, 'seed')"
            ),
            {"s": stock_id, "d": _D},
        )
        market = str(
            conn.execute(
                text("SELECT code FROM markets WHERE id=:m"), {"m": market_id}
            ).scalar_one()
        )
    yield market, index_code, stock_id
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id=:s"), {"s": stock_id})
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code=:ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE id=:s"), {"s": stock_id})
        conn.execute(text("DELETE FROM markets WHERE id=:m"), {"m": market_id})


def test_producer_reaches_a_subscriber_via_the_shared_bus(
    admin_engine: Engine, seeded: tuple[str, str, UUID]
) -> None:
    market, index_code, _ = seeded
    got: list[dict[str, object]] = []
    get_event_bus().subscribe("PricesValidated", lambda env: got.append(env))

    # A real producer, wired to the shared bus exactly as the jobs wire it.
    report = DataQualityService(get_event_bus()).validate(market, _D, _D, index_code=index_code)

    assert report.passed
    assert len(got) == 1  # the subscriber received the producer's event through the shared bus
    env = got[0]
    assert env["topic"] == "PricesValidated"
    payload = env["payload"]
    assert isinstance(payload, dict)
    assert payload["market"] == market and payload["stocks_validated"] == 1

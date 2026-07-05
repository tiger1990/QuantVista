"""Correction-handling self-heal proof (QV-027, 06 §5) — the Epic-3 capstone, real Postgres.

Ingest a filing → re-ingest a REVISED value → assert the full loop:
  (a) a new bitemporal version (PIT preserved: as_of T0 = original, as_of T2 = revised);
  (b) FundamentalsRevised emitted on the revision run only, carrying the affected (stock, period);
  (c) the correction consumer enqueues recompute_on_correction for that pair (self-heal).
Plus the recompute seam task runs under run_job. Throwaway stock, cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.core.events import InProcessEventBus
from quantvista.jobs.consumers import register_pipeline_consumers
from quantvista.jobs.corrections import _run_recompute, recompute_on_correction
from quantvista.jobs.framework import run_key
from quantvista.market_data.fundamentals import fundamentals_as_of
from quantvista.market_data.models import (
    CorporateAction,
    FundamentalSnapshot,
    LicenseClass,
    PriceBar,
    Provenance,
    ShareholdingSnapshot,
    UniverseEntry,
)
from quantvista.market_data.services import FundamentalsIngestionService

pytestmark = pytest.mark.integration

_PROV = Provenance("yfinance", None, LicenseClass.NON_COMMERCIAL_DEV)
_PERIOD = date(2025, 12, 31)
T0 = datetime(2026, 1, 15, tzinfo=UTC)  # original filing known
T2 = datetime(2026, 2, 10, tzinfo=UTC)  # restatement known


def _snap(symbol: str, pe: str) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        period_end=_PERIOD,
        statement_type="quarterly",
        pe=Decimal(pe),
        forward_pe=None,
        pb=None,
        roe=None,
        roce=None,
        debt_equity=None,
        provenance=_PROV,
    )


class _FakeProvider:
    def __init__(self, funds: dict[str, list[FundamentalSnapshot]]) -> None:
        self._funds = funds

    def get_fundamentals(self, symbol: str) -> Sequence[FundamentalSnapshot]:
        return self._funds.get(symbol, [])

    def get_prices(
        self, symbol: str, start: date, end: date, interval: str = "1d"
    ) -> Sequence[PriceBar]:
        return []

    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        return []

    def get_shareholding(self, symbol: str) -> Sequence[ShareholdingSnapshot]:
        return []

    def list_universe(self, index_code: str = "NIFTY200") -> Sequence[UniverseEntry]:
        return []


@pytest.fixture
def stock(admin_engine: Engine) -> Iterator[tuple[str, str, UUID]]:
    market_id, index_code, stock_id = uuid4(), f"TESTCORR_{uuid4().hex[:8]}", uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
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
        market = str(
            conn.execute(
                text("SELECT code FROM markets WHERE id=:m"), {"m": market_id}
            ).scalar_one()
        )
    yield market, index_code, stock_id
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM fundamentals WHERE stock_id=:s"), {"s": stock_id})
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code=:ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE id=:s"), {"s": stock_id})
        conn.execute(text("DELETE FROM markets WHERE code=:c"), {"c": market})
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "recompute:%"})


def test_correction_self_heals_end_to_end(
    admin_engine: Engine, stock: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    market, index_code, stock_id = stock
    enqueued: list[tuple[object, ...]] = []
    monkeypatch.setattr(recompute_on_correction, "delay", lambda *a: enqueued.append(a))

    bus = InProcessEventBus()  # real bus + real consumer → synchronous fan-out on publish
    register_pipeline_consumers(bus)

    # T0: original filing (pe=10) — an insert, not a revision → no FundamentalsRevised.
    FundamentalsIngestionService(_FakeProvider({"AAA": [_snap("AAA", "10")]}), bus).ingest(
        market, index_code=index_code, knowledge_time=T0
    )
    assert enqueued == []  # nothing to self-heal on first ingest

    # T2: restatement (pe=12) — a revision → FundamentalsRevised → recompute enqueued.
    report = FundamentalsIngestionService(_FakeProvider({"AAA": [_snap("AAA", "12")]}), bus).ingest(
        market, index_code=index_code, knowledge_time=T2
    )
    assert report.filings_revised == 1

    # (a) new bitemporal version — PIT preserved across the correction.
    with admin_engine.connect() as conn, Session(bind=conn) as session:
        as_of_t0 = fundamentals_as_of(session, stock_id, T0)
        as_of_t2 = fundamentals_as_of(session, stock_id, T2)
    assert as_of_t0 is not None and as_of_t0.ratios["pe"] == Decimal(
        "10.000000"
    )  # what we knew then
    assert as_of_t2 is not None and as_of_t2.ratios["pe"] == Decimal("12.000000")  # corrected value

    # (b) + (c) the revision drove exactly one recompute for the affected (stock, period).
    assert enqueued == [(str(stock_id), _PERIOD.isoformat(), "quarterly")]


def test_recompute_seam_enqueues_factor_recompute(
    admin_engine: Engine, stock: tuple[str, str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    from quantvista.jobs.scoring import compute_factors

    market, _, stock_id = stock
    enqueued: list[tuple[object, ...]] = []
    monkeypatch.setattr(compute_factors, "delay", lambda *a: enqueued.append(a))

    key = run_key("recompute", str(stock_id), _PERIOD.isoformat())
    outcome = _run_recompute(str(stock_id), _PERIOD.isoformat(), "quarterly", key)
    assert outcome.status.value == "succeeded"
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"), {"k": key}
        ).scalar_one()
    assert status == "succeeded"
    # self-heal: the correction enqueued a factor-snapshot recompute for the stock's market.
    assert len(enqueued) == 1 and enqueued[0][0] == market

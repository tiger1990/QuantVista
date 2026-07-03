"""ingest_daily_prices task + backfill wiring (QV-016) — provider monkeypatched, real Postgres.

Runs against the seeded NIFTY200 universe (12 stocks) with a fake provider (no network), proving
the task path: calendar/date → run_job (idempotent, jobs_runs) → service → upsert, and the
strict failure policy (any stock error → run fails). Cleans up rows by date + run_key.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs import ingest as ingest_mod
from quantvista.jobs.ingest import (
    IngestRunFailed,
    backfill_daily_prices,
    ingest_corporate_actions,
    ingest_daily_prices,
)
from quantvista.market_data.models import (
    CorporateAction,
    CorporateActionType,
    LicenseClass,
    PriceBar,
    Provenance,
)

pytestmark = pytest.mark.integration

_PROV = Provenance("yfinance", None, LicenseClass.NON_COMMERCIAL_DEV)
_TEST_DATE = date(2026, 6, 29)  # a weekday; explicit date bypasses the calendar


class _FakeYf:
    """Stands in for YFinanceDevProvider (constructed with no args in the task)."""

    _raise = False

    def get_prices(
        self, symbol: str, start: date, end: date, interval: str = "1d"
    ) -> Sequence[PriceBar]:
        if _FakeYf._raise:
            raise RuntimeError(f"provider down for {symbol}")
        c = Decimal("100.5")
        return [PriceBar(symbol, start, c, c, c, c, c, 100, _PROV)]

    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        if _FakeYf._raise:
            raise RuntimeError(f"provider down for {symbol}")
        return [
            CorporateAction(symbol, _TEST_DATE, CorporateActionType.SPLIT, Decimal(2), {}, _PROV)
        ]


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _FakeYf._raise = False
    monkeypatch.setattr(ingest_mod, "YFinanceDevProvider", _FakeYf)
    yield


@pytest.fixture
def _cleanup(admin_engine: Engine) -> Iterator[None]:
    yield
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE date = :d"), {"d": _TEST_DATE})
        conn.execute(
            text("DELETE FROM jobs_runs WHERE run_key LIKE :k"),
            {"k": f"prices:NSE:%{_TEST_DATE.isoformat()}%"},
        )


def test_ingest_task_succeeds_and_records(admin_engine: Engine, _cleanup: None) -> None:
    # Act — explicit date; eager .apply() runs the task in-process
    result = ingest_daily_prices.apply(args=["NSE", _TEST_DATE.isoformat()])
    # Assert — succeeded, jobs_runs recorded, prices upserted for the seeded universe
    assert result.get() == "succeeded"
    with admin_engine.connect() as conn:
        run = conn.execute(
            text("SELECT status, rows_out FROM jobs_runs WHERE run_key = :k"),
            {"k": f"prices:NSE:{_TEST_DATE.isoformat()}"},
        ).one()
        n = conn.execute(
            text("SELECT count(*) FROM daily_prices WHERE date = :d"), {"d": _TEST_DATE}
        ).scalar_one()
    assert run.status == "succeeded"
    assert n >= 1 and run.rows_out == n


def test_strict_failure_fails_the_run(admin_engine: Engine, _cleanup: None) -> None:
    # Arrange — every provider call errors
    _FakeYf._raise = True
    # Act / Assert — strict policy: the backfill (no Celery retry) raises, run marked failed
    with pytest.raises(IngestRunFailed):
        backfill_daily_prices("NSE", start=_TEST_DATE, end=_TEST_DATE)
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"),
            {"k": f"prices:NSE:backfill:{_TEST_DATE.isoformat()}:{_TEST_DATE.isoformat()}"},
        ).scalar_one()
    assert status == "failed"


@pytest.fixture
def _corpact_cleanup(admin_engine: Engine) -> Iterator[None]:
    yield
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM corporate_actions WHERE ex_date = :d"), {"d": _TEST_DATE})
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "corpact:NSE:%"})


def test_corporate_actions_task_ingests_and_records(
    admin_engine: Engine, _corpact_cleanup: None
) -> None:
    # Act — the corp-action task upserts a split for the seeded universe (explicit date)
    result = ingest_corporate_actions.apply(args=["NSE", _TEST_DATE.isoformat()])
    # Assert — succeeded, actions recorded in jobs_runs.rows_in + corporate_actions rows exist
    assert result.get() == "succeeded"
    with admin_engine.connect() as conn:
        run = conn.execute(
            text("SELECT status, rows_in FROM jobs_runs WHERE run_key = :k"),
            {"k": f"corpact:NSE:{_TEST_DATE.isoformat()}"},
        ).one()
        n = conn.execute(
            text("SELECT count(*) FROM corporate_actions WHERE ex_date = :d"), {"d": _TEST_DATE}
        ).scalar_one()
    assert run.status == "succeeded"
    assert n >= 1 and run.rows_in == n

"""Macro sync over real Postgres (QV-026) — fake provider (no network).

Proves the canonical re-stamp (stored series_code = the MacroSeries value, not the provider code),
idempotent upsert, and the task under run_job. Cleaned up by series_code / run_key.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs import macro as macro_mod
from quantvista.jobs.framework import run_key
from quantvista.jobs.macro import _run_macro
from quantvista.market_data.macro import MacroObservation, MacroSeries
from quantvista.market_data.services import MacroSyncService

pytestmark = pytest.mark.integration

_SERIES = MacroSeries.US_10Y  # stored key = "US_10Y"
_START, _END = date(2026, 1, 1), date(2026, 1, 3)


class _FakeMacro:
    def __init__(self, obs: Sequence[MacroObservation]) -> None:
        self._obs = obs

    def code_for(self, series: MacroSeries) -> str:
        return "FRED_CODE"  # provider code — must NOT be what we persist

    def get_series(self, series_code: str, start: date, end: date) -> Sequence[MacroObservation]:
        return self._obs


@pytest.fixture
def clean(admin_engine: Engine) -> Iterator[None]:
    yield
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM macro_series WHERE series_code = :s"), {"s": _SERIES.value})
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE :k"), {"k": "macro:%"})


def _obs(value: str | None) -> list[MacroObservation]:
    return [
        MacroObservation("FRED_CODE", _START, Decimal("4.5"), "fred"),
        MacroObservation("FRED_CODE", _END, Decimal(value) if value else None, "fred"),
    ]


def _rows(admin_engine: Engine) -> list[tuple[date, Decimal | None]]:
    with admin_engine.connect() as conn:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text("SELECT date, value FROM macro_series WHERE series_code = :s ORDER BY date"),
                {"s": _SERIES.value},
            )
        ]


def test_sync_stores_the_canonical_key(admin_engine: Engine, clean: None) -> None:
    report = MacroSyncService(_FakeMacro(_obs("4.8"))).sync(_SERIES, _START, _END)
    assert report.observations_upserted == 2 and report.series_code == "US_10Y"
    rows = _rows(admin_engine)  # persisted under the canonical key, not "FRED_CODE"
    assert rows == [(_START, Decimal("4.500000")), (_END, Decimal("4.800000"))]


def test_sync_is_idempotent(admin_engine: Engine, clean: None) -> None:
    MacroSyncService(_FakeMacro(_obs("4.8"))).sync(_SERIES, _START, _END)
    MacroSyncService(_FakeMacro(_obs("5.0"))).sync(_SERIES, _START, _END)  # corrected re-pull
    rows = _rows(admin_engine)
    assert len(rows) == 2 and rows[1][1] == Decimal("5.000000")  # updated in place, no dup


def test_task_runs_under_run_job(
    admin_engine: Engine, clean: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(macro_mod, "FredMacroProvider", lambda _key: _FakeMacro(_obs("4.8")))
    key = run_key("macro", _SERIES.value, uuid4().hex[:8])
    outcome = _run_macro(_SERIES, _START, _END, key)
    assert outcome.status.value == "succeeded"
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"), {"k": key}
        ).scalar_one()
    assert status == "succeeded"
    assert len(_rows(admin_engine)) == 2

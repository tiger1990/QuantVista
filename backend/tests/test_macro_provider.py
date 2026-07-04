"""Unit tests for the FRED macro adapter (market_data.macro, QV-026) — network-free.

A stubbed ``urlopen`` returns a canned FRED JSON payload, so the parse (incl. FRED's ``.`` missing
marker) is pinned without touching the network. Mirrors QV-012's fake-Ticker approach.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from quantvista.market_data.macro import (
    FRED_SERIES,
    WORLDBANK_SERIES,
    FredMacroProvider,
    MacroSeries,
    WorldBankMacroProvider,
)


class _FakeResp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _urlopen_with(payload: Any):  # type: ignore[no-untyped-def]
    data = json.dumps(payload).encode()

    def _open(url: str, timeout: float | None = None) -> _FakeResp:
        return _FakeResp(data)

    return _open


def test_fred_provider_parses_observations() -> None:
    payload = {
        "observations": [
            {"date": "2026-01-01", "value": "4.5"},
            {"date": "2026-01-02", "value": "."},  # FRED missing marker
        ]
    }
    provider = FredMacroProvider("test-key", urlopen=_urlopen_with(payload))
    obs = provider.get_series("DGS10", date(2026, 1, 1), date(2026, 1, 2))
    assert len(obs) == 2
    assert obs[0].series_code == "DGS10" and obs[0].date == date(2026, 1, 1)
    assert obs[0].value == Decimal("4.5") and obs[0].source == "fred"
    assert obs[1].value is None  # "." → None


def test_fred_provider_requires_an_api_key() -> None:
    with pytest.raises(RuntimeError, match="fred_api_key"):
        FredMacroProvider(None)


def test_fred_rejects_india_series() -> None:
    # India is NOT served from FRED (stale annual) — code_for must fail loudly, not return a code.
    with pytest.raises(ValueError, match="World Bank"):
        FredMacroProvider("test-key").code_for(MacroSeries.INDIA_CPI)


def test_worldbank_provider_parses_annual_observations() -> None:
    # World Bank envelope: [metadata, rows]; each row date is a YEAR → annual point at Jan 1.
    payload = [
        {"page": 1, "total": 2},
        [
            {"date": "2025", "value": 2.4},
            {"date": "2024", "value": None},  # missing → None
        ],
    ]
    provider = WorldBankMacroProvider(urlopen=_urlopen_with(payload))
    obs = provider.get_series("FP.CPI.TOTL.ZG", date(2024, 1, 1), date(2025, 12, 31))
    assert len(obs) == 2
    assert obs[0].date == date(2025, 1, 1) and obs[0].value == Decimal("2.4")
    assert obs[0].source == "worldbank"
    assert obs[1].value is None


def test_catalog_partitions_cleanly_across_providers() -> None:
    # Every canonical series has exactly one source; no series is served by both.
    assert FRED_SERIES.isdisjoint(WORLDBANK_SERIES)
    assert set(MacroSeries) == FRED_SERIES | WORLDBANK_SERIES

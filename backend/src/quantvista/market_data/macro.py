"""Macro time-series ingestion (QV-026) — generic provider seam + typed catalog.

Three layers (``02`` §7, rule #8): a typed ``MacroSeries`` catalog (canonical concepts), a
``MacroSyncService`` that drives sync, and the **generic** ``IMacroProvider.get_series`` seam that
fetches by a provider-native code — macro sources expose 10³–10⁶ series, so per-metric methods
don't scale. Each provider owns its canonical→code mapping (``code_for``); the persisted
``series_code`` is the **canonical** key (provider-stable), so a source swap never breaks factors.

Two real providers:
- **FRED** — US/global, all fresh (DGS10 is next-day). Free API key. FRED's *India* series are
  annual + lag >1 yr (re-hosted World Bank/IMF), so India is NOT served from FRED.
- **World Bank** — India + cross-country annual macro (GDP, CPI, inflation). No key; current-year.

Fast-follow (own stories, drop-in behind the same seam): **RBI** (monthly/daily rates, yields, FX) +
**MOSPI** (monthly CPI, IIP) for truly fresh Indian data; IMF for cross-country.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import certifi

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_WORLDBANK_URL = "https://api.worldbank.org/v2"
_RETRY_BACKOFF_S = 1.5


class MacroSeries(StrEnum):
    """Canonical macro concepts (stored ``series_code`` = the enum value; provider-stable)."""

    US_10Y = "US_10Y"
    US_FED_FUNDS = "US_FED_FUNDS"
    US_CPI = "US_CPI"
    INDIA_CPI = "INDIA_CPI"
    INDIA_INFLATION = "INDIA_INFLATION"
    INDIA_GDP = "INDIA_GDP"


# FRED = US/global only (all fresh). India is NOT here — FRED's India series lag >1 yr.
_FRED_CODES: dict[MacroSeries, str] = {
    MacroSeries.US_10Y: "DGS10",
    MacroSeries.US_FED_FUNDS: "FEDFUNDS",
    MacroSeries.US_CPI: "CPIAUCSL",
}

# World Bank = India + cross-country annual macro (no API key; current-year). Country IND for now.
_WORLDBANK_CODES: dict[MacroSeries, str] = {
    MacroSeries.INDIA_CPI: "FP.CPI.TOTL",
    MacroSeries.INDIA_INFLATION: "FP.CPI.TOTL.ZG",
    MacroSeries.INDIA_GDP: "NY.GDP.MKTP.CD",
}

FRED_SERIES: frozenset[MacroSeries] = frozenset(_FRED_CODES)
WORLDBANK_SERIES: frozenset[MacroSeries] = frozenset(_WORLDBANK_CODES)


@dataclass(frozen=True, slots=True)
class MacroObservation:
    """One point of a macro time series (maps 1:1 to ``macro_series``)."""

    series_code: str
    date: date
    value: Decimal | None
    source: str


@runtime_checkable
class IMacroProvider(Protocol):
    """Generic macro seam: resolve a canonical series to a provider code, then fetch points."""

    def code_for(self, series: MacroSeries) -> str: ...

    def get_series(
        self, series_code: str, start: date, end: date
    ) -> Sequence[MacroObservation]: ...


class _HttpJsonProvider:
    """Shared HTTP+JSON base: certifi trust store (works on macOS dev + Linux/CI) + retry.

    certifi supplies the CA bundle so TLS works everywhere (Homebrew Python on macOS doesn't use the
    system store). ``urlopen`` is injectable for network-free tests.
    """

    def __init__(self, urlopen: Callable[..., Any] | None = None) -> None:
        self._ctx = ssl.create_default_context(cafile=certifi.where())
        self._urlopen = urlopen or self._default_urlopen

    def _default_urlopen(self, url: str, timeout: float | None = None) -> Any:
        return urllib.request.urlopen(url, timeout=timeout, context=self._ctx)

    def _get_json(self, url: str, *, retries: int = 1) -> Any:
        for attempt in range(1, retries + 1):
            try:
                with self._urlopen(url, timeout=30) as resp:
                    return json.loads(resp.read())
            except Exception:  # transient (e.g. World Bank 502) — retry, else re-raise
                if attempt == retries:
                    raise
                time.sleep(_RETRY_BACKOFF_S)


class FredMacroProvider(_HttpJsonProvider):
    """FRED adapter (stdlib ``urllib`` + certifi; free + redistributable). US/global series only."""

    def __init__(self, api_key: str | None, *, urlopen: Callable[..., Any] | None = None) -> None:
        if not api_key:
            raise RuntimeError("FredMacroProvider needs a fred_api_key (set FRED_API_KEY)")
        super().__init__(urlopen)
        self._api_key = api_key

    def code_for(self, series: MacroSeries) -> str:
        try:
            return _FRED_CODES[series]
        except KeyError:
            raise ValueError(
                f"FRED has no fresh {series.value} series — India uses World Bank"
            ) from None

    def get_series(self, series_code: str, start: date, end: date) -> Sequence[MacroObservation]:
        params = urllib.parse.urlencode(
            {
                "series_id": series_code,
                "api_key": self._api_key,
                "file_type": "json",
                "observation_start": start.isoformat(),
                "observation_end": end.isoformat(),
            }
        )
        data = self._get_json(f"{_FRED_URL}?{params}")
        observations: list[MacroObservation] = []
        for obs in data.get("observations", []):
            raw = obs.get("value")
            value = None if raw in (None, ".", "") else Decimal(raw)  # FRED "." = missing
            observations.append(
                MacroObservation(series_code, date.fromisoformat(obs["date"]), value, "fred")
            )
        return observations


class WorldBankMacroProvider(_HttpJsonProvider):
    """World Bank Indicators adapter (no API key). India + cross-country **annual** macro.

    Response is a ``[metadata, rows]`` envelope; each row ``date`` is a **year** string → an annual
    point at Jan 1. The API is occasionally flaky (502), so reads retry.
    """

    def __init__(self, *, country: str = "IND", urlopen: Callable[..., Any] | None = None) -> None:
        super().__init__(urlopen)
        self._country = country

    def code_for(self, series: MacroSeries) -> str:
        try:
            return _WORLDBANK_CODES[series]
        except KeyError:
            raise ValueError(f"World Bank has no mapping for {series.value}") from None

    def get_series(self, series_code: str, start: date, end: date) -> Sequence[MacroObservation]:
        params = urllib.parse.urlencode(
            {"format": "json", "date": f"{start.year}:{end.year}", "per_page": 1000}
        )
        url = f"{_WORLDBANK_URL}/country/{self._country}/indicator/{series_code}?{params}"
        data = self._get_json(url, retries=3)
        rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
        observations: list[MacroObservation] = []
        for row in rows:
            raw = row.get("value")
            value = None if raw is None else Decimal(str(raw))
            observations.append(
                MacroObservation(series_code, date(int(row["date"]), 1, 1), value, "worldbank")
            )
        return observations

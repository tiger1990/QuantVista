"""Unit tests for the yfinance dev adapter (network-free via an injected ticker factory)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from quantvista.market_data.adapters.yfinance_dev import YFinanceDevProvider
from quantvista.market_data.interfaces import IMarketDataProvider
from quantvista.market_data.models import CorporateActionType, LicenseClass


class _FakeFrame:
    """Mimics the slice of the pandas DataFrame API the adapter uses."""

    def __init__(self, rows: list[tuple[datetime, dict[str, object]]]) -> None:
        self._rows = rows

    @property
    def empty(self) -> bool:
        return not self._rows

    def iterrows(self) -> object:
        return iter(self._rows)


class _FakeTicker:
    def __init__(
        self,
        history: _FakeFrame | None = None,
        actions: _FakeFrame | None = None,
        info: dict[str, object] | None = None,
    ) -> None:
        self._history = history if history is not None else _FakeFrame([])
        self.actions = actions if actions is not None else _FakeFrame([])
        self.info = info or {}

    def history(self, start: date, end: date, auto_adjust: bool) -> _FakeFrame:
        return self._history


def _provider(ticker: _FakeTicker) -> YFinanceDevProvider:
    return YFinanceDevProvider(ticker_factory=lambda _symbol: ticker)


def test_adapter_satisfies_provider_protocol() -> None:
    # Assert — runtime_checkable Protocol conformance (all 5 methods present)
    assert isinstance(_provider(_FakeTicker()), IMarketDataProvider)


def test_get_prices_maps_rows_to_decimal_bars_with_dev_license() -> None:
    # Arrange — one full row + one row with a NaN close
    frame = _FakeFrame(
        [
            (
                datetime(2026, 6, 30),
                {
                    "Open": 2900.1,
                    "High": 2950.0,
                    "Low": 2880.0,
                    "Close": 2940.55,
                    "Adj Close": 2940.55,
                    "Volume": 1_200_000.0,
                },
            ),
            (
                datetime(2026, 7, 1),
                {
                    "Open": 2941.0,
                    "High": 2960.0,
                    "Low": 2930.0,
                    "Close": float("nan"),
                    "Adj Close": float("nan"),
                    "Volume": 900_000.0,
                },
            ),
        ]
    )
    provider = _provider(_FakeTicker(history=frame))
    # Act
    bars = provider.get_prices("RELIANCE.NS", date(2026, 6, 1), date(2026, 7, 2))
    # Assert
    assert len(bars) == 2
    assert bars[0].date == date(2026, 6, 30)
    assert isinstance(bars[0].close, Decimal) and bars[0].close == Decimal("2940.55")
    assert bars[0].volume == 1_200_000  # int, not float
    assert bars[1].close is None  # NaN → None, no crash
    # AC #4: every datum is hard-stamped as non-commercial dev
    assert all(b.provenance.license_class is LicenseClass.NON_COMMERCIAL_DEV for b in bars)
    assert bars[0].provenance.source == "yfinance"


def test_get_prices_empty_history_returns_empty() -> None:
    # Arrange / Act
    bars = _provider(_FakeTicker(history=_FakeFrame([]))).get_prices(
        "X", date(2026, 1, 1), date(2026, 1, 2)
    )
    # Assert
    assert bars == []


def test_get_corporate_actions_maps_and_filters_by_date() -> None:
    # Arrange — a dividend in range, a split in range, and one out of range
    actions = _FakeFrame(
        [
            (datetime(2026, 5, 2), {"Dividends": 18.0, "Stock Splits": 0.0}),
            (datetime(2026, 6, 10), {"Dividends": 0.0, "Stock Splits": 2.0}),
            (datetime(2026, 1, 1), {"Dividends": 5.0, "Stock Splits": 0.0}),  # out of range
        ]
    )
    provider = _provider(_FakeTicker(actions=actions))
    # Act
    events = provider.get_corporate_actions("INFY.NS", date(2026, 4, 1), date(2026, 6, 30))
    # Assert
    kinds = {(e.action_type, e.ratio_or_amount) for e in events}
    assert (CorporateActionType.DIVIDEND, Decimal("18.0")) in kinds
    assert (CorporateActionType.SPLIT, Decimal("2.0")) in kinds
    assert len(events) == 2  # out-of-range dividend excluded


def test_get_fundamentals_maps_info_with_sparse_none() -> None:
    # Arrange — trailingPE present, forwardPE absent
    ticker = _FakeTicker(info={"trailingPE": 28.4, "priceToBook": 12.1, "returnOnEquity": 0.42})
    # Act
    (snap,) = _provider(ticker).get_fundamentals("TCS.NS")
    # Assert
    assert snap.pe == Decimal("28.4")
    assert snap.forward_pe is None
    assert snap.provenance.license_class is LicenseClass.NON_COMMERCIAL_DEV


def test_get_shareholding_best_effort_and_empty_when_absent() -> None:
    # Arrange
    with_data = _FakeTicker(info={"heldPercentInsiders": 0.723})
    without = _FakeTicker(info={})
    # Act
    (held,) = _provider(with_data).get_shareholding("TCS.NS")
    empty = _provider(without).get_shareholding("TCS.NS")
    # Assert — insiders 0.723 → 72.3% promoter; FII/DII not splittable → None; absent → []
    assert held.promoter_holding == Decimal("72.300")
    assert held.fii_holding is None
    assert empty == []


def test_list_universe_returns_dev_licensed_entries() -> None:
    # Act
    universe = _provider(_FakeTicker()).list_universe()
    # Assert
    assert len(universe) >= 5
    assert all(e.exchange == "NSE" for e in universe)
    assert all(e.provenance.license_class is LicenseClass.NON_COMMERCIAL_DEV for e in universe)

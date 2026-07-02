"""Unit tests for the vendor-agnostic market-data DTOs (market_data.models)."""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

import pytest

from quantvista.market_data.models import (
    CorporateAction,
    CorporateActionType,
    FundamentalSnapshot,
    LicenseClass,
    PriceBar,
    Provenance,
    ShareholdingSnapshot,
    UniverseEntry,
)

_DEV_PROV = Provenance(
    source="yfinance",
    source_url="https://finance.yahoo.com/quote/RELIANCE.NS",
    license_class=LicenseClass.NON_COMMERCIAL_DEV,
)


def test_price_bar_holds_decimal_money_and_is_frozen() -> None:
    # Arrange / Act
    bar = PriceBar(
        symbol="RELIANCE.NS",
        date=date(2026, 6, 30),
        open=Decimal("2900.10"),
        high=Decimal("2950.00"),
        low=Decimal("2880.00"),
        close=Decimal("2940.55"),
        adj_close=Decimal("2940.55"),
        volume=1_200_000,
        provenance=_DEV_PROV,
    )
    # Assert — money is Decimal (never float), and the DTO is immutable
    assert isinstance(bar.close, Decimal)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bar.close = Decimal("1")  # type: ignore[misc]


def test_optional_price_fields_accept_none() -> None:
    # Arrange / Act — yfinance often returns sparse rows
    bar = PriceBar(
        symbol="X",
        date=date(2026, 1, 1),
        open=None,
        high=None,
        low=None,
        close=None,
        adj_close=None,
        volume=None,
        provenance=_DEV_PROV,
    )
    # Assert
    assert bar.close is None and bar.volume is None


def test_corporate_action_type_and_amount() -> None:
    # Arrange / Act
    action = CorporateAction(
        symbol="INFY.NS",
        ex_date=date(2026, 5, 2),
        action_type=CorporateActionType.DIVIDEND,
        ratio_or_amount=Decimal("18.00"),
        details={"currency": "INR"},
        provenance=_DEV_PROV,
    )
    # Assert
    assert action.action_type is CorporateActionType.DIVIDEND
    assert isinstance(action.ratio_or_amount, Decimal)


def test_fundamental_and_shareholding_snapshots_allow_sparse_fields() -> None:
    # Arrange / Act
    fund = FundamentalSnapshot(
        symbol="TCS.NS",
        period_end=date(2026, 3, 31),
        statement_type="annual",
        pe=Decimal("28.4"),
        forward_pe=None,
        pb=Decimal("12.1"),
        roe=Decimal("0.42"),
        roce=None,
        debt_equity=None,
        provenance=_DEV_PROV,
    )
    hold = ShareholdingSnapshot(
        symbol="TCS.NS",
        as_of_date=date(2026, 3, 31),
        promoter_holding=Decimal("72.3"),
        fii_holding=None,
        dii_holding=None,
        public_holding=None,
        pledged_pct=None,
        provenance=_DEV_PROV,
    )
    # Assert
    assert fund.forward_pe is None and isinstance(fund.pe, Decimal)
    assert hold.fii_holding is None and isinstance(hold.promoter_holding, Decimal)


def test_universe_entry_carries_provenance() -> None:
    # Arrange / Act
    entry = UniverseEntry(
        symbol="HDFCBANK.NS",
        name="HDFC Bank",
        isin="INE040A01034",
        exchange="NSE",
        is_active=True,
        provenance=_DEV_PROV,
    )
    # Assert
    assert entry.provenance.license_class is LicenseClass.NON_COMMERCIAL_DEV


def test_license_class_value_is_stable_contract() -> None:
    # The stored string is an audited contract (03 §1 license_class) — pin it.
    assert LicenseClass.NON_COMMERCIAL_DEV.value == "non_commercial_dev"

"""market_data — vendor-agnostic domain DTOs (QV-012).

These are the return types of ``IMarketDataProvider``: immutable, vendor-neutral records
that the rest of the codebase sees instead of any yfinance/pandas type. Money and ratios
are ``Decimal`` (never ``float`` — project rule); dates are ``date``; sparse/unreliable
upstream fields degrade to ``None``. Every record carries ``Provenance`` (``source``,
``source_url``, ``license_class``) — the audit trail that makes "can we redistribute this?"
answerable (``plans/03`` §1). Field shapes mirror the eventual ``03`` §4 schema; persistence
(DTO → row, with ``stock_id``/``ingested_at``) lands in QV-013+/QV-016.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class LicenseClass(Enum):
    """Redistribution class of a datum's source. The string value is an audited contract."""

    NON_COMMERCIAL_DEV = "non_commercial_dev"  # yfinance/Yahoo — internal dev only, never paid
    COMMERCIAL_LICENSED = "commercial_licensed"  # a licensed vendor (QV-072); may back paid tiers


class CorporateActionType(Enum):
    SPLIT = "split"
    BONUS = "bonus"
    DIVIDEND = "dividend"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a datum came from + whether it may be redistributed (``plans/03`` §1 rule 2)."""

    source: str
    source_url: str | None
    license_class: LicenseClass


@dataclass(frozen=True, slots=True)
class PriceBar:
    """One trading day's OHLCV for a symbol. ``close`` and ``adj_close`` are kept distinct."""

    symbol: str
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    adj_close: Decimal | None
    volume: int | None
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """A split / bonus / dividend (needed later to compute adjusted close, QV-017)."""

    symbol: str
    ex_date: date
    action_type: CorporateActionType
    ratio_or_amount: Decimal
    details: dict[str, str]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class FundamentalSnapshot:
    """Point-in-time fundamentals/ratios for a symbol (bitemporal persistence is QV-021)."""

    symbol: str
    period_end: date | None
    statement_type: str | None
    pe: Decimal | None
    forward_pe: Decimal | None
    pb: Decimal | None
    roe: Decimal | None
    roce: Decimal | None
    debt_equity: Decimal | None
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class ShareholdingSnapshot:
    """PIT ownership breakdown for a symbol (percentages)."""

    symbol: str
    as_of_date: date
    promoter_holding: Decimal | None
    fii_holding: Decimal | None
    dii_holding: Decimal | None
    public_holding: Decimal | None
    pledged_pct: Decimal | None
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class UniverseEntry:
    """One member of a tradable universe (e.g. a NIFTY200 constituent)."""

    symbol: str
    name: str | None
    isin: str | None
    exchange: str
    is_active: bool
    provenance: Provenance

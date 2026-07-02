"""Market Data (reference) published interfaces.

Global/reference domain: no ``tenant_id``, no RLS, written only by background jobs.
External vendors enter ONLY through ``IMarketDataProvider`` so they can be swapped
without touching analytics (data-licensing seam).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from quantvista.market_data.models import (
    CorporateAction,
    FundamentalSnapshot,
    PriceBar,
    ShareholdingSnapshot,
    UniverseEntry,
)


@runtime_checkable
class IMarketDataProvider(Protocol):
    """Vendor-agnostic source of market data (the adapter boundary, ``plans/03`` §1).

    Every external vendor enters ONLY through this interface, so swapping vendors is a new
    adapter with zero analytics changes. Methods are symbol-based (no ``stock_id`` — the DB
    is built later, QV-013+) and return the immutable DTOs from ``market_data.models``.
    """

    def get_prices(self, symbol: str, start: date, end: date) -> Sequence[PriceBar]: ...

    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]: ...

    def get_fundamentals(self, symbol: str) -> Sequence[FundamentalSnapshot]: ...

    def get_shareholding(self, symbol: str) -> Sequence[ShareholdingSnapshot]: ...

    def list_universe(self, index_code: str = "NIFTY200") -> Sequence[UniverseEntry]: ...


@runtime_checkable
class IPriceRepository(Protocol):
    """Read access to ``daily_prices`` (monthly range-partitioned)."""

    def close_on(self, stock_id: UUID, on: date) -> Decimal | None: ...


@runtime_checkable
class IFundamentalsRepository(Protocol):
    """Point-in-time (bitemporal) read access to ``fundamentals``."""

    def as_of(self, stock_id: UUID, knowledge_date: date) -> object | None: ...

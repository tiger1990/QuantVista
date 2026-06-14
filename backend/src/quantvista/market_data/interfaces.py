"""Market Data (reference) published interfaces.

Global/reference domain: no ``tenant_id``, no RLS, written only by background jobs.
External vendors enter ONLY through ``IMarketDataProvider`` so they can be swapped
without touching analytics (data-licensing seam).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class IMarketDataProvider(Protocol):
    """Vendor-agnostic source of prices/fundamentals (adapter boundary)."""

    def fetch_daily_prices(self, symbol: str, on: date) -> object: ...


@runtime_checkable
class IPriceRepository(Protocol):
    """Read access to ``daily_prices`` (monthly range-partitioned)."""

    def close_on(self, stock_id: UUID, on: date) -> Decimal | None: ...


@runtime_checkable
class IFundamentalsRepository(Protocol):
    """Point-in-time (bitemporal) read access to ``fundamentals``."""

    def as_of(self, stock_id: UUID, knowledge_date: date) -> object | None: ...

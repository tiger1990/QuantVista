"""Portfolio & Risk published interfaces.

Tenant-scoped domain (RLS-enforced). Depends on Analytics (through interfaces).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class IPortfolioService(Protocol):
    """CRUD + queries over a tenant's portfolios and positions."""

    def holdings(self, portfolio_id: UUID) -> object: ...


@runtime_checkable
class IOptimizer(Protocol):
    """Allocation optimizer (Ledoit-Wolf shrinkage covariance).

    Infeasible problems raise/return the binding constraint, never a silent result.
    """

    def optimize(self, spec: dict[str, Any]) -> dict[UUID, Decimal]: ...


@runtime_checkable
class IRiskEngine(Protocol):
    """Risk metrics for a portfolio (vol, drawdown, contributions)."""

    def metrics(self, portfolio_id: UUID) -> dict[str, Decimal]: ...

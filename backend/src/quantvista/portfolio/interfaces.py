"""Portfolio & Risk published interfaces.

Tenant-scoped domain (RLS-enforced). Depends on Analytics (through interfaces).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from quantvista.market_data.returns import ReturnsMatrix
    from quantvista.portfolio.optimizer import OptimizationRequest, OptimizationResult


@runtime_checkable
class IPortfolioService(Protocol):
    """CRUD + queries over a tenant's portfolios and positions."""

    def holdings(self, portfolio_id: UUID) -> object: ...


@runtime_checkable
class IOptimizer(Protocol):
    """Allocation optimizer (Ledoit-Wolf shrinkage covariance).

    Infeasible problems raise ``InfeasibleConstraints`` with the binding constraint — never a
    silent or degenerate result (US-03). Implemented by ``MeanVarianceOptimizer`` (QV-054);
    risk-parity / Black-Litterman implementations arrive with later Epic-7 stories.
    """

    def optimize(
        self, request: OptimizationRequest, returns: ReturnsMatrix
    ) -> OptimizationResult: ...


@runtime_checkable
class IRiskEngine(Protocol):
    """Risk metrics for a portfolio (vol, drawdown, contributions)."""

    def metrics(self, portfolio_id: UUID) -> dict[str, Decimal]: ...

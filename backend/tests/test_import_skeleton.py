"""Smoke tests proving the module skeleton imports cleanly and exposes its interfaces.

These are the meaningful tests for QV-001: they confirm every bounded context is
importable (so import-linter and the app can build the module graph) and that each
context publishes its declared interfaces. The dependency-DAG itself is enforced by
import-linter (`backend/.importlinter`), proven separately in the story's gate check.
"""

from __future__ import annotations

import importlib

import pytest

CONTEXTS = [
    "core",
    "identity",
    "market_data",
    "news",
    "analytics",
    "portfolio",
    "alerts",
    "schemas",
    "api",
    "jobs",
]

# Published interfaces per context (plans/02-architecture.md §4).
PUBLISHED_INTERFACES = {
    "core": ["IEventBus", "IAuditLogger"],
    "identity": ["IAuthService", "IEntitlementService", "ITenantContext"],
    "market_data": ["IMarketDataProvider", "IPriceRepository", "IFundamentalsRepository"],
    "news": ["INewsService", "ISentimentService"],
    "analytics": ["IScoreEngine", "IFactor", "IBacktestEngine"],
    "portfolio": ["IPortfolioService", "IOptimizer", "IRiskEngine"],
    "alerts": ["IAlertService", "INotificationChannel"],
}


@pytest.mark.parametrize("context", CONTEXTS)
def test_context_imports(context: str) -> None:
    # Arrange / Act
    module = importlib.import_module(f"quantvista.{context}")
    # Assert
    assert module is not None


@pytest.mark.parametrize(("context", "names"), PUBLISHED_INTERFACES.items())
def test_published_interfaces_exist(context: str, names: list[str]) -> None:
    # Arrange / Act
    interfaces = importlib.import_module(f"quantvista.{context}.interfaces")
    # Assert
    for name in names:
        assert hasattr(interfaces, name), f"{context}.interfaces missing {name}"


def test_response_envelope_shape() -> None:
    # Arrange
    from quantvista.schemas.envelope import Envelope

    # Act
    ok = Envelope.ok({"value": 1})
    fail: Envelope[object] = Envelope.fail("validation_error", "bad input")

    # Assert
    assert ok.success is True and ok.error is None
    assert fail.success is False and fail.data is None
    assert fail.error is not None and fail.error.code == "validation_error"

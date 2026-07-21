"""Risk endpoint wire DTOs (QV-058).

``GET /portfolios/{id}/risk`` response. **Pure** Pydantic DTOs — the foundation-purity import-linter
contract forbids ``schemas`` from importing a domain context, so the ``RiskMetrics`` → DTO mapping
lives in the ``api`` layer. Series metrics are ``str | None`` (null on thin/degenerate history);
``beta_coverage`` surfaces how many holdings had a usable beta. Money/ratios serialize as strings,
never ``float``.
"""

from __future__ import annotations

from pydantic import BaseModel


class BetaCoverageDTO(BaseModel):
    covered: int
    total: int
    ratio: str


class RiskResponse(BaseModel):
    as_of_date: str
    beta: str | None
    volatility: str | None
    max_drawdown: str | None
    sharpe: str | None
    sortino: str | None
    hhi: str
    sector_exposure: dict[str, str]  # sector → Decimal-as-string weight
    beta_coverage: BetaCoverageDTO


__all__ = ["BetaCoverageDTO", "RiskResponse"]

"""portfolio — RiskEngine (QV-058).

Portfolio risk metrics so a user understands their exposure: **beta, annualized volatility, max
drawdown, Sharpe, Sortino, concentration (HHI), sector exposure**. Pure compute over a PIT returns
matrix + weights — no DB, no I/O (the api layer supplies positions, the returns matrix, per-stock
betas, sectors, and latest closes), so it's unit-testable in isolation. `portfolio` may import
`market_data` types (the DAG allows it; already done by `optimization/base.py`); this module does
**not** import `analytics` — per-stock `beta_1y` is read via a `market_data` repo, not the scorer.

Weights are **market-value with a target fallback** (settled decision): `wᵢ = shares_i·close_i / Σ`,
falling back to `target_weight` (then equal-weight as a degenerate guard) only when the whole book
has no market value. Compute in float64; quantize out to Decimal at the boundary — money/ratios on
the wire are Decimal, never float. Series metrics degrade to ``None`` (never fabricated 0 / inf /
NaN) on thin history or a degenerate series; beta/HHI/sector still compute from weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import numpy as np

from quantvista.market_data.returns import ReturnsMatrix
from quantvista.portfolio.services import WEIGHT_SUM_EPSILON

_TRADING_DAYS = 252
_Q = Decimal("0.000001")  # numeric(9,6) / numeric(18,6) — quantize ratios to 6 dp
_VOL_EPSILON = 1e-12  # guard Sharpe/Sortino denominators: a degenerate series has std ~1e-15, not 0


def _q(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(_Q, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BetaCoverage:
    """How many held names had a usable ``beta_1y`` (the rest are excluded + renormalized)."""

    covered: int
    total: int
    ratio: Decimal


@dataclass(frozen=True)
class RiskMetrics:
    """Portfolio risk snapshot. Series metrics are ``None`` when history is too thin/degenerate."""

    beta: Decimal | None
    volatility: Decimal | None
    max_drawdown: Decimal | None
    sharpe: Decimal | None
    sortino: Decimal | None
    hhi: Decimal
    sector_exposure: dict[str, Decimal]
    beta_coverage: BetaCoverage


def _weights(
    positions: list[dict[str, object]], closes: dict[UUID, Decimal]
) -> dict[UUID, Decimal]:
    """Market-value weights (`shares·close`), normalized. Fall back to ``target_weight`` only when
    the whole book has no market value; equal-weight is the last-resort degenerate guard."""
    sids = [UUID(str(p["stock_id"])) for p in positions]

    mv: dict[UUID, Decimal] = {}
    for p, sid in zip(positions, sids, strict=True):
        shares = p.get("shares")
        close = closes.get(sid)
        mv[sid] = (
            Decimal(str(shares)) * close
            if (shares is not None and close is not None)
            else Decimal(0)
        )
    total_mv = sum(mv.values(), Decimal(0))
    if total_mv > 0:
        return {sid: v / total_mv for sid, v in mv.items()}

    tw = {
        sid: Decimal(str(p.get("target_weight") or 0))
        for p, sid in zip(positions, sids, strict=True)
    }
    total_tw = sum(tw.values(), Decimal(0))
    if total_tw > 0:
        return {sid: v / total_tw for sid, v in tw.items()}

    equal = Decimal(1) / Decimal(len(positions))  # no shares AND no targets → equal-weight
    return {sid: equal for sid in sids}


class RiskEngine:
    """Computes portfolio risk metrics from a PIT returns matrix + market-value weights."""

    def metrics(
        self,
        positions: list[dict[str, object]],
        returns: ReturnsMatrix,
        betas: dict[UUID, Decimal | None],
        sectors: dict[UUID, str],
        closes: dict[UUID, Decimal],
        *,
        risk_free_rate: Decimal = Decimal(0),
    ) -> RiskMetrics:
        weights = _weights(positions, closes)
        assert abs(sum(weights.values(), Decimal(0)) - Decimal(1)) <= WEIGHT_SUM_EPSILON

        hhi = _q(sum((w * w for w in weights.values()), Decimal(0)))

        sector_exposure: dict[str, Decimal] = {}
        for sid, w in weights.items():
            sector = sectors.get(sid)
            if sector is not None:
                sector_exposure[sector] = sector_exposure.get(sector, Decimal(0)) + w
        sector_exposure = {s: _q(w) for s, w in sector_exposure.items()}

        beta, coverage = self._beta(weights, betas)
        series = self._series_metrics(weights, returns, risk_free_rate)

        return RiskMetrics(
            beta=beta,
            hhi=hhi,
            sector_exposure=sector_exposure,
            beta_coverage=coverage,
            **series,
        )

    def _beta(
        self, weights: dict[UUID, Decimal], betas: dict[UUID, Decimal | None]
    ) -> tuple[Decimal | None, BetaCoverage]:
        """Portfolio beta = Σ wᵢ·βᵢ over held names with a beta, renormalized over covered names."""
        held = {sid: w for sid, w in weights.items() if w > 0}
        covered = {sid: w for sid, w in held.items() if betas.get(sid) is not None}
        total = len(held)
        cov_ratio = _q(Decimal(len(covered)) / Decimal(total)) if total else Decimal(0)
        coverage = BetaCoverage(covered=len(covered), total=total, ratio=cov_ratio)

        cov_weight = sum(covered.values(), Decimal(0))
        if not covered or cov_weight <= 0:
            return None, coverage
        beta = sum(
            ((w / cov_weight) * betas[sid] for sid, w in covered.items()),  # type: ignore[operator]
            Decimal(0),
        )
        return _q(beta), coverage

    def _series_metrics(
        self, weights: dict[UUID, Decimal], returns: ReturnsMatrix, risk_free_rate: Decimal
    ) -> dict[str, Decimal | None]:
        """Volatility / max drawdown / Sharpe / Sortino from the portfolio daily return series.

        Weights are aligned to the returns matrix's surviving columns (thin names are dropped by the
        PIT reader) and renormalized over survivors. ``None`` for every metric when history is too
        thin or the sub-portfolio has no weight."""
        none: dict[str, Decimal | None] = dict.fromkeys(
            ("volatility", "max_drawdown", "sharpe", "sortino")
        )
        ids = returns.stock_ids
        if len(ids) == 0 or returns.values.shape[0] < 2:
            return none

        w_sub = np.array([float(weights.get(sid, Decimal(0))) for sid in ids], dtype=np.float64)
        w_total = w_sub.sum()
        if w_total <= _VOL_EPSILON:
            return none
        w_sub = w_sub / w_total

        r_p = returns.values @ w_sub  # portfolio daily return series
        rf = float(risk_free_rate)
        ann_return = float(r_p.mean()) * _TRADING_DAYS
        std = float(r_p.std(ddof=1))
        ann_vol = std * np.sqrt(_TRADING_DAYS)

        # Max drawdown of the equity curve (starting NAV = 1), as a positive magnitude.
        equity = np.concatenate([[1.0], np.cumprod(1.0 + r_p)])
        drawdowns = equity / np.maximum.accumulate(equity) - 1.0
        max_dd = float(-drawdowns.min())

        downside = np.sqrt(float(np.mean(np.minimum(r_p, 0.0) ** 2))) * np.sqrt(_TRADING_DAYS)

        return {
            "volatility": _q(ann_vol),
            "max_drawdown": _q(max_dd),
            "sharpe": _q((ann_return - rf) / ann_vol) if ann_vol > _VOL_EPSILON else None,
            "sortino": _q((ann_return - rf) / downside) if downside > _VOL_EPSILON else None,
        }


__all__ = ["BetaCoverage", "RiskEngine", "RiskMetrics"]

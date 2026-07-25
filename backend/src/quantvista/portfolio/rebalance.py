"""portfolio — RebalanceEngine (QV-059).

Pure compute: given positions (with shares + optional target_weight) and PIT closes,
compute market-value drift from targets and return suggested trades.

Weight basis: market-value (shares_i×close_i/Σ), same as RiskEngine (QV-058) — reuses
``compute_portfolio_weights`` from ``portfolio.risk``. Only positions WITH a
``target_weight`` participate in drift; those without a target contribute to total
market value but have no target to drift from.

Target weights are normalized to sum to 1 before computing drift (handles partial sets
where the user only set targets for some positions). Total drift is the total-variation
distance: Σ|w_current_i − t_normalized_i| / 2, which lies in [0, 0.5].

``portfolio_total_drift`` is a standalone public helper imported by
``alerts.repositories`` (DAG-legal: alerts → portfolio) for drift alert evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from quantvista.portfolio.risk import compute_portfolio_weights

_Q = Decimal("0.000001")  # 6-dp quantize — matches risk.py
_DEFAULT_DRIFT_THRESHOLD = Decimal("0.05")  # 5% per-name default


def _q(x: Decimal) -> Decimal:
    return x.quantize(_Q, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TradeSuggestion:
    """One position that breaches the drift threshold and needs trading."""

    stock_id: UUID
    symbol: str
    direction: str  # "buy" | "sell"
    current_weight: Decimal  # quantized 6dp
    target_weight: Decimal  # normalized target, quantized 6dp
    delta_weight: Decimal  # target − current (positive = buy, negative = sell), 6dp


@dataclass(frozen=True)
class RebalancePlan:
    """The full rebalancing suggestion for a portfolio at a point in time."""

    as_of_date: str
    total_drift: Decimal  # Σ|Δw_i|/2 over targeted positions; 0 = balanced
    needs_rebalance: bool  # total_drift > drift_threshold
    trades: list[TradeSuggestion]  # sorted descending by |delta_weight|


def portfolio_total_drift(
    positions: list[dict[str, object]],
    closes: dict[UUID, Decimal],
) -> Decimal | None:
    """Σ|w_current_i − t_normalized_i|/2 over positions with ``target_weight``.

    Returns ``None`` when no position has a target (nothing to drift from). Used by
    ``alerts.repositories.portfolio_drift_metrics`` for drift alert evaluation.
    """
    weights = compute_portfolio_weights(positions, closes)
    targeted = [
        (UUID(str(p["stock_id"])), Decimal(str(p["target_weight"])))
        for p in positions
        if p.get("target_weight") is not None
    ]
    if not targeted:
        return None
    total_target = sum((tw for _, tw in targeted), Decimal(0))
    if total_target <= 0:
        return None
    drift_sum = sum(
        (abs(weights.get(sid, Decimal(0)) - tw / total_target) for sid, tw in targeted), Decimal(0)
    )
    return _q(drift_sum / 2)


class RebalanceEngine:
    """Computes trade suggestions needed to reach target weights within a drift threshold."""

    def suggest(
        self,
        positions: list[dict[str, object]],
        closes: dict[UUID, Decimal],
        as_of_date: str,
        *,
        drift_threshold: Decimal = _DEFAULT_DRIFT_THRESHOLD,
    ) -> RebalancePlan | None:
        """Return a ``RebalancePlan`` or ``None`` when no positions have target weights.

        Only positions with ``|w_current − t_normalized| > drift_threshold`` appear in
        ``trades``; others are considered in balance. Trades sorted descending by
        ``|delta_weight|`` (largest mis-allocation first).
        """
        weights = compute_portfolio_weights(positions, closes)

        targeted = [
            (
                UUID(str(p["stock_id"])),
                Decimal(str(p["target_weight"])),
                str(p.get("symbol") or ""),
            )
            for p in positions
            if p.get("target_weight") is not None
        ]
        if not targeted:
            return None

        total_target = sum(tw for _, tw, _ in targeted)
        if total_target <= 0:
            return None

        trades: list[TradeSuggestion] = []
        drift_sum = Decimal(0)

        for sid, raw_tw, symbol in targeted:
            t_norm = raw_tw / total_target
            w_curr = weights.get(sid, Decimal(0))
            delta = t_norm - w_curr
            abs_drift = abs(delta)
            drift_sum += abs_drift
            if abs_drift > drift_threshold:
                trades.append(
                    TradeSuggestion(
                        stock_id=sid,
                        symbol=symbol,
                        direction="buy" if delta > 0 else "sell",
                        current_weight=_q(w_curr),
                        target_weight=_q(t_norm),
                        delta_weight=_q(delta),
                    )
                )

        total_drift = _q(drift_sum / 2)
        trades.sort(key=lambda t: abs(t.delta_weight), reverse=True)

        return RebalancePlan(
            as_of_date=as_of_date,
            total_drift=total_drift,
            needs_rebalance=total_drift > drift_threshold,
            trades=trades,
        )


__all__ = [
    "RebalanceEngine",
    "RebalancePlan",
    "TradeSuggestion",
    "portfolio_total_drift",
]

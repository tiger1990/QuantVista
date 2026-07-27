"""PIT data access for backtests (QV-063) — the look-ahead firewall for the engine (QV-065).

Given a rebalance date ``as_of``, this is the ONLY seam the backtest engine reads through, and every
method is bounded by knowledge ≤ ``as_of``. It **composes** the existing as-of readers — it does not
re-implement scoring or price access:

- ``ranked_universe`` reuses ``analytics.scoring.compute_universe``, which runs the Factor/Score
  engines through ``ScoringContext`` (the QV-037 look-ahead defence: bitemporal fundamentals at
  end-of-``as_of``-day knowledge-time, indicators/sentiment ``date <= as_of``).
- ``returns_as_of`` reuses ``market_data.returns.returns_matrix_as_of`` (already ``date <= as_of``).

There is deliberately **no** "latest"/unbounded read here, so the engine is *structurally* unable to
see post-``as_of`` data (proven by the leakage regression test). Survivorship-free membership is
QV-064 — ``universe`` is caller-supplied; the rebalance loop + frictions are QV-065.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from quantvista.analytics.scoring import compute_universe
from quantvista.market_data.returns import ReturnsMatrix, returns_matrix_as_of

# The score fields a backtest may rank by (mirrors BacktestSpec.rank_by / StockScore attributes).
_RANK_FIELDS = frozenset({"composite", "fundamental", "momentum", "quality", "sentiment", "risk"})


class BacktestDataAccess:
    """Point-in-time reads for one backtest. All methods are bounded by knowledge ≤ ``as_of``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ranked_universe(
        self,
        as_of: date,
        universe: Sequence[UUID],
        *,
        rank_by: str = "composite",
        top_n: int,
    ) -> list[UUID]:
        """The top-``top_n`` stock ids by the ``rank_by`` score, computed PIT at ``as_of``.

        Names with no score for the metric are excluded (not imputed). Deterministic: ties break by
        stock_id, so a fixed ``(as_of, universe, rank_by, top_n)`` over unchanged data is stable.
        """
        if rank_by not in _RANK_FIELDS:
            raise ValueError(f"rank_by must be one of {sorted(_RANK_FIELDS)}, got {rank_by!r}")
        scores = compute_universe(self._session, universe, as_of)
        scored = [
            (value, s.stock_id)
            for s in scores
            if (value := getattr(s, rank_by)) is not None  # exclude unscored names
        ]
        scored.sort(key=lambda t: (-t[0], t[1]))  # score desc, then stock_id asc (deterministic)
        return [stock_id for _, stock_id in scored[:top_n]]

    def returns_as_of(
        self,
        as_of: date,
        stock_ids: Sequence[UUID],
        *,
        lookback_days: int | None = None,
        min_observations: int = 2,
    ) -> ReturnsMatrix:
        """PIT adjusted-return matrix (``date <= as_of``). Thin names are dropped + reported."""
        return returns_matrix_as_of(
            self._session,
            stock_ids,
            as_of,
            lookback_days=lookback_days,
            min_observations=min_observations,
        )


__all__ = ["BacktestDataAccess"]

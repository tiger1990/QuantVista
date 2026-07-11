"""ScoringContext (QV-028) — the point-in-time data gateway for factors.

Factors receive *only* this context — never a ``Session`` or a repository — so they physically
cannot read "latest" data: every read is bounded by ``as_of``. The structural defence against
look-ahead bias (``05`` §1.1). Fundamentals use the QV-021 bitemporal read (knowledge-time = end
of the ``as_of`` day, so a later restatement is invisible); indicators use ``date <= as_of``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from quantvista.market_data.fundamentals import FundamentalVersion, fundamentals_as_of
from quantvista.market_data.repositories import technical_indicators_as_of


class ScoringContext:
    """PIT-only reads for factor computation at a single ``as_of`` date."""

    def __init__(self, session: Session, as_of: date, universe: Sequence[UUID]) -> None:
        self._session = session
        self.as_of = as_of
        self._universe = tuple(universe)

    def universe(self) -> tuple[UUID, ...]:
        """The stock ids in scope at ``as_of`` (membership resolved by the caller)."""
        return self._universe

    def fundamentals_as_of(
        self, stock_id: UUID, as_of: date, *, statement_type: str | None = None
    ) -> FundamentalVersion | None:
        """The fundamentals version *known* by end of the ``as_of`` day (QV-021 bitemporal).

        Cadence-agnostic by default (``None``) so scoring picks up whatever the dev source ingests
        (QV-095 emits ``annual``); the bitemporal knowledge-time guard still applies.
        """
        knowledge_time = datetime.combine(as_of, time.max, tzinfo=UTC)
        return fundamentals_as_of(
            self._session, stock_id, knowledge_time, statement_type=statement_type
        )

    def indicator_as_of(self, stock_id: UUID, as_of: date) -> dict[str, Decimal | None] | None:
        """The latest technical-indicator row with ``date <= as_of`` (no future-dated row)."""
        return technical_indicators_as_of(self._session, stock_id, as_of)

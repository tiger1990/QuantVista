"""Factor unit tests (QV-028) — fake PIT context, no DB.

Pins each factor's metadata (key/category/direction), that it reads the right PIT field, and the
None-on-missing policy. The ScoringContext is faked (reads overridden) so factors run without a DB.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantvista.analytics.context import ScoringContext
from quantvista.analytics.factors import (
    ALL_FACTORS,
    BetaFactor,
    DebtEquityFactor,
    FactorCategory,
    PEFactor,
    Return6MFactor,
    ROEFactor,
    Vol30DFactor,
)
from quantvista.market_data.fundamentals import FundamentalVersion

_SID = uuid4()
_AS_OF = date(2026, 1, 20)
_EMPTY_RATIOS: dict[str, Decimal | None] = {
    "pe": None,
    "forward_pe": None,
    "pb": None,
    "roe": None,
    "roce": None,
    "debt_equity": None,
}


def _fund(**ratios: Decimal) -> FundamentalVersion:
    return FundamentalVersion(
        id=1,
        stock_id=_SID,
        period_end=date(2025, 12, 31),
        statement_type="quarterly",
        reported_at=None,
        knowledge_from=datetime(2026, 1, 15, tzinfo=UTC),
        knowledge_to=None,
        ratios={**_EMPTY_RATIOS, **ratios},
    )


class _FakeCtx(ScoringContext):
    def __init__(
        self,
        *,
        fundamentals: FundamentalVersion | None = None,
        indicators: dict[str, Decimal | None] | None = None,
    ) -> None:
        self._f = fundamentals
        self._i = indicators

    def fundamentals_as_of(
        self, stock_id: object, as_of: object, *, statement_type: str | None = None
    ) -> FundamentalVersion | None:
        return self._f

    def indicator_as_of(self, stock_id: object, as_of: object) -> dict[str, Decimal | None] | None:
        return self._i


def test_fundamental_factor_reads_ratio_with_metadata() -> None:
    ctx = _FakeCtx(fundamentals=_fund(pe=Decimal("15.5"), roe=Decimal("0.22")))
    assert (PEFactor().key, PEFactor().category, PEFactor().direction) == (
        "pe",
        FactorCategory.FUNDAMENTAL,
        -1,
    )
    assert PEFactor().compute(ctx, _SID, _AS_OF) == 15.5
    assert ROEFactor().compute(ctx, _SID, _AS_OF) == pytest.approx(0.22)
    assert (ROEFactor().category, ROEFactor().direction) == (FactorCategory.QUALITY, 1)
    assert DebtEquityFactor().direction == -1  # lower leverage is better


def test_indicator_factor_reads_column() -> None:
    ctx = _FakeCtx(
        indicators={"ret_6m": Decimal("0.12"), "beta_1y": Decimal("1.10"), "vol_30d": None}
    )
    assert Return6MFactor().compute(ctx, _SID, _AS_OF) == pytest.approx(0.12)
    assert (Return6MFactor().category, Return6MFactor().direction) == (FactorCategory.MOMENTUM, 1)
    assert BetaFactor().compute(ctx, _SID, _AS_OF) == pytest.approx(1.10)
    assert BetaFactor().direction == -1
    assert Vol30DFactor().compute(ctx, _SID, _AS_OF) is None  # column present but null


def test_none_when_source_missing() -> None:
    empty = _FakeCtx(fundamentals=None, indicators=None)
    assert PEFactor().compute(empty, _SID, _AS_OF) is None  # no fundamentals version
    assert Return6MFactor().compute(empty, _SID, _AS_OF) is None  # no indicator row
    assert PEFactor().compute(_FakeCtx(fundamentals=_fund()), _SID, _AS_OF) is None  # ratio is null


def test_all_factors_cover_categories_with_unique_keys() -> None:
    assert len(ALL_FACTORS) == 11
    assert len({f.key for f in ALL_FACTORS}) == 11  # keys unique
    categories = {f.category for f in ALL_FACTORS}
    # QV-046 added the sentiment factor → all five categories now have ≥1 concrete factor.
    assert categories == {
        FactorCategory.FUNDAMENTAL,
        FactorCategory.MOMENTUM,
        FactorCategory.QUALITY,
        FactorCategory.SENTIMENT,
        FactorCategory.RISK,
    }

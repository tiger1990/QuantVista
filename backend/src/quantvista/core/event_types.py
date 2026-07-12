"""Typed domain events (QV-024) — producer-side construction; dict on the wire.

Each event is a frozen dataclass with ``TOPIC`` / ``VERSION`` + ``to_payload`` / ``from_payload`` —
the payload is the JSON-safe dict carried in the envelope. Producers build these type-safely; the
bus stamps the envelope and moves the dict; handlers read ``payload`` (and may rehydrate via
``from_payload``). ``core`` foundation — imports no bounded context.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Self


@dataclass(frozen=True, slots=True)
class _Event:
    """Base: JSON-safe ``to_payload`` / ``from_payload`` (fields must be JSON primitives)."""

    TOPIC: ClassVar[str]
    VERSION: ClassVar[int]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class PricesIngested(_Event):
    TOPIC: ClassVar[str] = "PricesIngested"
    VERSION: ClassVar[int] = 1
    market: str
    start: str
    end: str
    stocks_ok: int
    rows_upserted: int


@dataclass(frozen=True, slots=True)
class PricesValidated(_Event):
    TOPIC: ClassVar[str] = "PricesValidated"
    VERSION: ClassVar[int] = 1
    market: str
    start: str
    end: str
    stocks_validated: int
    expected_stocks: int


@dataclass(frozen=True, slots=True)
class FundamentalsUpdated(_Event):
    TOPIC: ClassVar[str] = "FundamentalsUpdated"
    VERSION: ClassVar[int] = 1
    market: str
    knowledge_time: str
    inserted: int
    revised: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class FundamentalsRevised(_Event):
    """Fires only when ≥1 filing is *revised* — the correction signal that drives self-heal (QV-027,
    ``06`` §5). ``revisions`` = the affected filings whose derived scores must recompute."""

    TOPIC: ClassVar[str] = "FundamentalsRevised"
    VERSION: ClassVar[int] = 1
    market: str
    knowledge_time: str
    revisions: tuple[dict[str, str], ...]  # [{stock_id, period_end, statement_type}]


@dataclass(frozen=True, slots=True)
class IndicatorsComputed(_Event):
    TOPIC: ClassVar[str] = "IndicatorsComputed"
    VERSION: ClassVar[int] = 1
    market: str
    date: str
    stocks: int


@dataclass(frozen=True, slots=True)
class FactorsComputed(_Event):
    # Rich metadata (model_version + counts) so downstream can judge snapshot completeness/identity.
    TOPIC: ClassVar[str] = "FactorsComputed"
    VERSION: ClassVar[int] = 1
    market: str
    date: str
    model_version: str
    stock_count: int  # stocks with ≥1 factor value in the snapshot
    factor_count: int  # total factor_values rows persisted


@dataclass(frozen=True, slots=True)
class ScoresComputed(_Event):
    TOPIC: ClassVar[str] = "ScoresComputed"
    VERSION: ClassVar[int] = 1
    universe: str
    date: str
    model_version: str
    count: int  # stocks scored


@dataclass(frozen=True, slots=True)
class NewsScored(_Event):
    TOPIC: ClassVar[str] = "NewsScored"
    VERSION: ClassVar[int] = 1
    news_batch: str
    count: int


@dataclass(frozen=True, slots=True)
class AlertsFired(_Event):
    TOPIC: ClassVar[str] = "AlertsFired"
    VERSION: ClassVar[int] = 1
    date: str  # the cycle date (dedup key)
    trigger: str  # 'scores' | 'news'
    count: int  # new alert_events written

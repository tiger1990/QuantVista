"""Bitemporal fundamentals repository (QV-021) — the point-in-time credibility backbone (03 §5).

Two time axes: ``period_end`` (valid-time — which fiscal period the numbers describe) and
``knowledge_from``/``knowledge_to`` (knowledge-time — when we knew them). A score for a knowledge
instant reads the version whose interval contains it; a restatement **closes** the prior version
and **inserts** a new one — history is never destructively updated. Global table → privileged
engine; ratios stay ``Decimal``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.orm import Session

# Allowlist of NUMERIC ratio/measure columns (0005). The write builds its column list from THIS
# set only (values always parametrised) — never from caller-supplied names — so a dict-driven
# insert can't inject SQL.
_RATIO_COLUMNS: frozenset[str] = frozenset(
    {
        "pe",
        "forward_pe",
        "pb",
        "roe",
        "roce",
        "roic",
        "debt_equity",
        "revenue",
        "revenue_growth",
        "eps",
        "eps_growth",
        "fcf",
        "fcf_growth",
        "operating_margin",
        "net_margin",
        "current_ratio",
        "quick_ratio",
        "ev_ebitda",
        "peg",
        "price_sales",
        "enterprise_value",
    }
)
_RATIO_SQL_LIST = ", ".join(sorted(_RATIO_COLUMNS))
_SELECT_COLS = (
    "id, stock_id, period_end, statement_type, reported_at, knowledge_from, knowledge_to, "
    + _RATIO_SQL_LIST
)

RecordAction = Literal["inserted", "revised", "unchanged"]


@dataclass(frozen=True, slots=True)
class FundamentalVersion:
    id: int
    stock_id: UUID
    period_end: date
    statement_type: str
    reported_at: datetime | None
    knowledge_from: datetime
    knowledge_to: datetime | None
    ratios: dict[str, Decimal | None]


_AS_OF_SQL = text(
    f"""
    SELECT {_SELECT_COLS} FROM fundamentals
    WHERE stock_id = :stock_id AND statement_type = :statement_type
      AND knowledge_from <= :as_of
      AND (knowledge_to IS NULL OR :as_of < knowledge_to)
    ORDER BY period_end DESC, knowledge_from DESC
    LIMIT 1
    """
)
_OPEN_VERSION_SQL = text(
    f"""
    SELECT {_SELECT_COLS} FROM fundamentals
    WHERE stock_id = :stock_id AND period_end = :period_end
      AND statement_type = :statement_type AND knowledge_to IS NULL
    """
)
_CLOSE_OPEN_SQL = text(
    """
    UPDATE fundamentals SET knowledge_to = :knowledge_time
    WHERE stock_id = :stock_id AND period_end = :period_end
      AND statement_type = :statement_type AND knowledge_to IS NULL
    """
)


def _to_version(m: RowMapping) -> FundamentalVersion:
    return FundamentalVersion(
        id=int(m["id"]),
        stock_id=m["stock_id"],
        period_end=m["period_end"],
        statement_type=str(m["statement_type"]),
        reported_at=m["reported_at"],
        knowledge_from=m["knowledge_from"],
        knowledge_to=m["knowledge_to"],
        ratios={c: m[c] for c in _RATIO_COLUMNS},
    )


def fundamentals_as_of(
    session: Session,
    stock_id: UUID,
    as_of: datetime,
    *,
    statement_type: str = "quarterly",
) -> FundamentalVersion | None:
    """The version whose knowledge interval contains ``as_of`` (newest ``period_end`` first)."""
    row = (
        session.execute(
            _AS_OF_SQL,
            {"stock_id": stock_id, "statement_type": statement_type, "as_of": as_of},
        )
        .mappings()
        .one_or_none()
    )
    return _to_version(row) if row is not None else None


def record_fundamental_version(
    session: Session,
    stock_id: UUID,
    period_end: date,
    statement_type: str,
    ratios: Mapping[str, Decimal | None],
    *,
    reported_at: datetime | None = None,
    knowledge_time: datetime | None = None,
) -> RecordAction:
    """Version a filing bitemporally: first → ``inserted``; changed → ``revised`` (close prior +
    insert new); identical → ``unchanged`` (no write). Never overwrites ratio columns in place."""
    unknown = set(ratios) - _RATIO_COLUMNS
    if unknown:
        raise ValueError(f"unknown ratio column(s): {sorted(unknown)}")
    kt = knowledge_time or datetime.now(UTC)

    current = (
        session.execute(
            _OPEN_VERSION_SQL,
            {"stock_id": stock_id, "period_end": period_end, "statement_type": statement_type},
        )
        .mappings()
        .one_or_none()
    )

    if current is not None and all(current[c] == ratios.get(c) for c in _RATIO_COLUMNS):
        return "unchanged"

    action: RecordAction = "revised" if current is not None else "inserted"
    if current is not None:
        session.execute(
            _CLOSE_OPEN_SQL,
            {
                "knowledge_time": kt,
                "stock_id": stock_id,
                "period_end": period_end,
                "statement_type": statement_type,
            },
        )

    cols = [c for c in sorted(_RATIO_COLUMNS) if c in ratios]
    col_sql = "".join(f", {c}" for c in cols)
    val_sql = "".join(f", :{c}" for c in cols)
    params: dict[str, object] = {
        "stock_id": stock_id,
        "period_end": period_end,
        "statement_type": statement_type,
        "reported_at": reported_at,
        "knowledge_from": kt,
    }
    for c in cols:
        params[c] = ratios[c]
    insert_sql = (
        "INSERT INTO fundamentals "
        f"(stock_id, period_end, statement_type, reported_at, knowledge_from{col_sql}) VALUES "
        f"(:stock_id, :period_end, :statement_type, :reported_at, :knowledge_from{val_sql})"
    )
    session.execute(text(insert_sql), params)
    return action

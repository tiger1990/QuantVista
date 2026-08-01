"""Monthly range-partition maintenance (QV-104).

The migrations create only the **current and next** month for each range-partitioned table, and
`db/README.md` says to *schedule* `create_month_partition(...)` from then on — but nothing did. The
failure is silent: PostgreSQL routes a row with no matching partition into the `_default` partition
rather than erroring, so from the second month after a deploy every price/indicator/score row lands
there. Partition pruning is quietly lost and the default table grows without bound. Demonstrated on
a real database: a row dated two months out landed in ``daily_prices_default``.

Parents are **discovered from the catalog** rather than listed here, so a table partitioned in a
future migration is maintained automatically instead of being forgotten. Only RANGE partitions keyed
on a single date/timestamp column are touched — anything else is not a monthly scheme, so it is
skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

#: How many months beyond the current one to keep ready. Three gives ample slack for a missed run
#: (the job is idempotent, so overlap is free) without creating a long tail of empty partitions.
DEFAULT_MONTHS_AHEAD = 3

# Range-partitioned tables keyed on a single date/timestamp column. `partstrat = 'r'` is RANGE;
# `relkind = 'p'` excludes partitioned *indexes*, which also appear in the inheritance catalogs.
_PARTITIONED_PARENTS_SQL = text(
    """
    SELECT c.relname AS parent
    FROM pg_partitioned_table pt
    JOIN pg_class c ON c.oid = pt.partrelid AND c.relkind = 'p'
    JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
    JOIN pg_attribute a
      ON a.attrelid = c.oid
     AND a.attnum = pt.partattrs[0]
    WHERE pt.partstrat = 'r'
      AND array_length(pt.partattrs, 1) = 1
      AND a.atttypid IN ('date'::regtype, 'timestamp'::regtype, 'timestamptz'::regtype)
    ORDER BY c.relname
    """
)

_MISSING_COVER_SQL = text(
    """
    SELECT NOT EXISTS (
        SELECT 1
        FROM pg_inherits i
        JOIN pg_class part ON part.oid = i.inhrelid
        WHERE i.inhparent = to_regclass(:parent)
          AND part.relname = :expected
    ) AS missing
    """
)


@dataclass(frozen=True, slots=True)
class PartitionMaintenanceResult:
    """What one maintenance run touched — surfaced in the job ledger for observability."""

    parents: tuple[str, ...]
    months: tuple[date, ...]

    @property
    def ensured(self) -> int:
        return len(self.parents) * len(self.months)


def _month_start(on: date) -> date:
    return on.replace(day=1)


def _next_month(month_start: date) -> date:
    return (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )


def upcoming_months(today: date, months_ahead: int = DEFAULT_MONTHS_AHEAD) -> list[date]:
    """The current month plus ``months_ahead`` following month-starts."""
    months = [_month_start(today)]
    for _ in range(months_ahead):
        months.append(_next_month(months[-1]))
    return months


def partitioned_parents(session: Session) -> list[str]:
    """Every date-range-partitioned table in ``public``, discovered from the catalog."""
    return [row.parent for row in session.execute(_PARTITIONED_PARENTS_SQL)]


def partition_name(parent: str, month_start: date) -> str:
    """Mirrors the naming in the ``create_month_partition`` SQL helper."""
    return f"{parent}_{month_start:%Y_%m}"


def parents_missing_cover(session: Session, on: date) -> list[str]:
    """Parents with no partition covering ``on`` — i.e. rows for that date fall to ``_default``."""
    missing = []
    for parent in partitioned_parents(session):
        expected = partition_name(parent, _month_start(on))
        if session.execute(
            _MISSING_COVER_SQL, {"parent": parent, "expected": expected}
        ).scalar_one():
            missing.append(parent)
    return missing


def ensure_month_partitions(
    session: Session, *, today: date | None = None, months_ahead: int = DEFAULT_MONTHS_AHEAD
) -> PartitionMaintenanceResult:
    """Create the current + next ``months_ahead`` monthly partitions for every partitioned parent.

    Idempotent: the SQL helper is ``CREATE TABLE IF NOT EXISTS``, so re-running is a no-op and a
    missed run self-heals on the next tick.
    """
    months = upcoming_months(today or date.today(), months_ahead)
    parents = partitioned_parents(session)
    for parent in parents:
        for month in months:
            session.execute(
                text("SELECT create_month_partition(:parent, :month)"),
                {"parent": parent, "month": month},
            )
    return PartitionMaintenanceResult(parents=tuple(parents), months=tuple(months))


__all__ = [
    "DEFAULT_MONTHS_AHEAD",
    "PartitionMaintenanceResult",
    "ensure_month_partitions",
    "parents_missing_cover",
    "partition_name",
    "partitioned_parents",
    "upcoming_months",
]

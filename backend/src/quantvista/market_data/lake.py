"""Data-lake price offload + read path (QV-067).

Export historical ``daily_prices`` to Parquet partitions (``/{market}/{table}/{year}/{month}/``) and
read them back with **DuckDB** in the exact shape the backtest engine consumes, so an analytical
sweep scans columnar Parquet instead of a Postgres row scan (03 §7).

- ``export_prices_parquet`` writes decimal-typed Parquet (exact, no float drift), a file per month.
- ``ParquetPriceSource.panel`` returns ``{stock_id: {date: adj_close}}`` — byte-identical to
  ``repositories.adjusted_close_panel`` — so ``BacktestDataAccess`` is source-agnostic.

``pyarrow``/``duckdb`` are an optional ``[lake]`` extra, imported lazily.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.core.objectstore import ObjectStore

_TABLE = "daily_prices"


class PriceSource(Protocol):
    """The read seam the engine's ``price_panel`` delegates to (Postgres or Parquet)."""

    def panel(
        self, stock_ids: Sequence[UUID], start: date, end: date
    ) -> dict[UUID, dict[date, Decimal]]: ...


_EXPORT_SQL = text(
    """
    SELECT dp.stock_id, dp.date, dp.adj_close
    FROM daily_prices dp
    JOIN stocks s  ON s.id = dp.stock_id
    JOIN markets m ON m.id = s.market_id
    WHERE m.code = :market AND dp.adj_close IS NOT NULL
      AND (CAST(:until AS date) IS NULL OR dp.date <= CAST(:until AS date))
    ORDER BY dp.date
    """
)


def export_prices_parquet(
    session: Session, store: ObjectStore, market: str, *, until: date | None = None
) -> int:
    """Write ``market``'s ``daily_prices`` to monthly Parquet partitions. Returns rows written.

    Idempotent: each ``{year}/{month}`` partition file is overwritten wholesale.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = session.execute(_EXPORT_SQL, {"market": market, "until": until}).all()
    by_month: dict[tuple[int, int], list[tuple[UUID, date, Decimal]]] = defaultdict(list)
    for stock_id, bar_date, adj_close in rows:
        by_month[(bar_date.year, bar_date.month)].append((stock_id, bar_date, adj_close))

    schema = pa.schema(
        [("stock_id", pa.string()), ("date", pa.date32()), ("adj_close", pa.decimal128(20, 8))]
    )
    written = 0
    for (year, month), part in by_month.items():
        table = pa.table(
            {
                "stock_id": pa.array([str(s) for s, _, _ in part], pa.string()),
                "date": pa.array([d for _, d, _ in part], pa.date32()),
                "adj_close": pa.array([a for _, _, a in part], pa.decimal128(20, 8)),
            },
            schema=schema,
        )
        store.fs.create_dir(store.partition_dir(market, _TABLE, year, month), recursive=True)
        pq.write_table(
            table, store.partition_file(market, _TABLE, year, month), filesystem=store.fs
        )
        written += len(part)
    return written


class ParquetPriceSource:
    """PIT price panel read from Parquet via DuckDB. Bound to one ``market`` (a backtest is
    single-market); shape matches ``adjusted_close_panel`` exactly."""

    def __init__(self, store: ObjectStore, market: str) -> None:
        self._store = store
        self._market = market

    def panel(
        self, stock_ids: Sequence[UUID], start: date, end: date
    ) -> dict[UUID, dict[date, Decimal]]:
        if not stock_ids or not self._store.table_exists(self._market, _TABLE):
            return {}
        import duckdb

        glob = self._store.read_glob(self._market, _TABLE)
        con = duckdb.connect()
        try:
            rows = con.execute(
                "SELECT stock_id, date, adj_close FROM read_parquet(?) "
                "WHERE stock_id = ANY(?) AND date >= ? AND date <= ?",
                [glob, [str(s) for s in stock_ids], start, end],
            ).fetchall()
        finally:
            con.close()
        panel: dict[UUID, dict[date, Decimal]] = {}
        for stock_id, bar_date, adj_close in rows:
            panel.setdefault(UUID(stock_id), {})[bar_date] = adj_close
        return panel


__all__ = ["ParquetPriceSource", "PriceSource", "export_prices_parquet"]

"""Benchmark: Parquet/DuckDB vs Postgres for backtest price reads (QV-067).

Informational dev tool (NOT a CI test — perf asserts are flaky). Exports the dev universe's
``daily_prices`` to the local-fs Parquet store, then times two access patterns honestly:

- **selective panel** (``stock_id = ANY + date BETWEEN`` — the engine's per-backtest read): an
  *indexed point-range* lookup, so Postgres is competitive/faster. Parquet is not a win here.
- **analytical scan** (aggregate every row in a multi-year window — 03 §7's "multi-factor sweep"):
  a *full scan*, where DuckDB's columnar Parquet read is far faster than a Postgres scan.

The measurable speedup lives in the second pattern; the first is shown so the trade-off is clear.

Run from ``backend/`` with the venv + ``[lake]`` extra:  python scripts/bench_parquet_read.py
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import duckdb
from sqlalchemy import text

from quantvista.core.config import get_settings
from quantvista.core.db import privileged_session_scope
from quantvista.core.objectstore import get_object_store
from quantvista.market_data.lake import ParquetPriceSource, export_prices_parquet
from quantvista.market_data.repositories import adjusted_close_panel

MARKET = "NSE"


def main() -> None:
    end = date.today()
    start = end - timedelta(days=365 * 5)  # a 5-year window
    store = get_object_store(get_settings())

    with privileged_session_scope() as session:
        ids = list(
            session.execute(
                text(
                    "SELECT s.id FROM stocks s JOIN markets m ON m.id = s.market_id "
                    "WHERE m.code = :mkt"
                ),
                {"mkt": MARKET},
            ).scalars()
        )
        print(f"universe: {len(ids)} stocks, window {start}..{end}")

        t0 = time.perf_counter()
        rows = export_prices_parquet(session, store, MARKET)
        print(f"export: {rows} rows in {time.perf_counter() - t0:.2f}s\n")

        # 1) selective panel — Postgres's indexed sweet spot
        t0 = time.perf_counter()
        pg_panel = adjusted_close_panel(session, ids, start, end)
        pg_panel_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        pq_panel = ParquetPriceSource(store, MARKET).panel(ids, start, end)
        pq_panel_s = time.perf_counter() - t0
        print("selective panel (engine read — indexed point-range):")
        print(
            f"  postgres {pg_panel_s * 1000:6.1f} ms | duckdb {pq_panel_s * 1000:6.1f} ms"
            f" | {pg_panel_s / pq_panel_s:.2f}x | equivalent={pq_panel == pg_panel}\n"
        )

        # 2) analytical full scan — the data-lake use case (03 §7)
        t0 = time.perf_counter()
        session.execute(
            text(
                "SELECT count(*), avg(adj_close) FROM daily_prices dp "
                "JOIN stocks s ON s.id = dp.stock_id JOIN markets m ON m.id = s.market_id "
                "WHERE m.code = :mkt AND dp.date >= :d"
            ),
            {"mkt": MARKET, "d": start},
        ).one()
        pg_scan_s = time.perf_counter() - t0

    glob = store.read_glob(MARKET, "daily_prices")
    con = duckdb.connect()
    t0 = time.perf_counter()
    con.execute(
        "SELECT count(*), avg(adj_close) FROM read_parquet(?) WHERE date >= ?", [glob, start]
    ).fetchone()
    pq_scan_s = time.perf_counter() - t0
    print("analytical scan (multi-factor sweep — full scan):")
    print(
        f"  postgres {pg_scan_s * 1000:6.1f} ms | duckdb {pq_scan_s * 1000:6.1f} ms"
        f" | {pg_scan_s / pq_scan_s:.2f}x faster"
    )


if __name__ == "__main__":
    main()

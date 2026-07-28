"""Parquet offload + DuckDB read path (QV-067) — real Postgres, real Parquet.

Proves the DuckDB Parquet panel is **byte-identical** to the Postgres ``adjusted_close_panel`` (so
the engine is source-agnostic), spans multiple monthly partitions, and stays PIT-bounded. The engine
metrics are identical across sources *by construction* — the only source-dependent input is
``price_panel``, asserted equal here. Committed-then-cleaned seed. Gated on the ``[lake]`` extra.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("duckdb")
pytestmark = pytest.mark.integration

from pathlib import Path  # noqa: E402

from sqlalchemy import Engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from quantvista.analytics.backtest_data import BacktestDataAccess  # noqa: E402
from quantvista.core.config import Settings  # noqa: E402
from quantvista.core.objectstore import ObjectStore, get_object_store  # noqa: E402
from quantvista.market_data.lake import ParquetPriceSource, export_prices_parquet  # noqa: E402
from quantvista.market_data.repositories import adjusted_close_panel  # noqa: E402

_START = date(2024, 1, 1)
_END = date(2024, 2, 29)  # two monthly partitions (Jan + Feb)


@pytest.fixture
def seeded(admin_engine: Engine) -> Iterator[tuple[Session, str, list[UUID]]]:
    market_id = uuid4()
    market_code = f"BT{uuid4().hex[:6]}"
    ids = [uuid4(), uuid4()]
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": market_code},
        )
        rows = []
        for j, sid in enumerate(ids):
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name) "
                    "VALUES (:id, :m, :s, 'Co')"
                ),
                {"id": sid, "m": market_id, "s": f"BT{uuid4().hex[:6]}"},
            )
            for d in (date(2024, 1, 10), date(2024, 1, 20), date(2024, 2, 5)):
                px = Decimal(f"{100 + j}.{d.day:02d}")
                rows.append({"s": sid, "d": d, "c": px})
        conn.execute(
            text(
                "INSERT INTO daily_prices "
                "(stock_id, date, close, adj_close, high, low, volume, source) "
                "VALUES (:s, :d, :c, :c, :c, :c, 100, 'seed')"
            ),
            rows,
        )
    engine_conn = admin_engine.connect()
    try:
        with Session(bind=engine_conn) as session:
            yield session, market_code, ids
    finally:
        engine_conn.close()
        with admin_engine.begin() as conn:
            conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:s)"), {"s": ids})
            conn.execute(text("DELETE FROM stocks WHERE id = ANY(:s)"), {"s": ids})
            conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})


def _store(tmp: Path) -> ObjectStore:
    return get_object_store(Settings(object_store_backend="local", object_store_root=str(tmp)))


def test_parquet_panel_equals_postgres(
    seeded: tuple[Session, str, list[UUID]], tmp_path: Path
) -> None:
    session, market, ids = seeded
    store = _store(tmp_path)
    written = export_prices_parquet(session, store, market)
    assert written == 6  # 2 stocks × 3 bars

    pg = adjusted_close_panel(session, ids, _START, _END)
    pq = ParquetPriceSource(store, market).panel(ids, _START, _END)
    assert pq == pg  # byte-identical shape + values → engine is source-agnostic
    assert set(pq) == set(ids) and all(len(pq[i]) == 3 for i in ids)


def test_multiple_month_partitions_written(
    seeded: tuple[Session, str, list[UUID]], tmp_path: Path
) -> None:
    session, market, _ = seeded
    store = _store(tmp_path)
    export_prices_parquet(session, store, market)
    assert Path(store.partition_file(market, "daily_prices", 2024, 1)).exists()  # Jan
    assert Path(store.partition_file(market, "daily_prices", 2024, 2)).exists()  # Feb


def test_parquet_source_is_pit_bounded(
    seeded: tuple[Session, str, list[UUID]], tmp_path: Path
) -> None:
    session, market, ids = seeded
    store = _store(tmp_path)
    export_prices_parquet(session, store, market)
    panel = ParquetPriceSource(store, market).panel(ids, _START, date(2024, 1, 31))
    assert all(max(panel[i]) <= date(2024, 1, 31) for i in panel)  # the Feb bar is invisible


def test_data_access_delegates_to_parquet(
    seeded: tuple[Session, str, list[UUID]], tmp_path: Path
) -> None:
    session, market, ids = seeded
    store = _store(tmp_path)
    export_prices_parquet(session, store, market)
    via_pg = BacktestDataAccess(session).price_panel(_START, _END, ids)
    via_pq = BacktestDataAccess(
        session, price_source=ParquetPriceSource(store, market)
    ).price_panel(_START, _END, ids)
    assert via_pq == via_pg  # the seam swap is transparent


def test_parquet_source_empty_when_not_exported(
    seeded: tuple[Session, str, list[UUID]], tmp_path: Path
) -> None:
    _, market, ids = seeded
    store = _store(tmp_path)  # nothing exported
    assert ParquetPriceSource(store, market).panel(ids, _START, _END) == {}


def test_export_task_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The Celery task wrapper: privileged session → export → ledgered outcome (idempotent)."""
    from quantvista.core.config import get_settings
    from quantvista.jobs.lake import export_prices_parquet as task

    monkeypatch.setenv("OBJECT_STORE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert task("NSE") in {"succeeded", "skipped"}  # runs end-to-end (0+ rows on a fresh DB)
    finally:
        get_settings.cache_clear()

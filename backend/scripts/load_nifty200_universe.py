"""Dev-only: load the full Nifty 200 into the dev reference tables (QV-092).

Reads the bundled NSE constituent snapshot (``scripts/data/nifty200.csv``) and idempotently upserts
``stocks`` + open ``NIFTY200`` ``index_constituents`` so the dev universe is the real ~200 names
instead of the 12-stock bootstrap seed.

DEV ONLY: current-snapshot membership, no index weights, ``sector`` = the NSE ``Industry`` column.
The authoritative point-in-time membership + weights arrive with the licensed vendor (QV-072); this
loader must never drive a production constituent sync. Idempotent (re-run leaves counts unchanged).

Usage (from ``backend/`` with the venv active)::

    python scripts/load_nifty200_universe.py [--market NSE]
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from quantvista.core.db import privileged_session_scope

logging.basicConfig(level=logging.INFO, format="[load_nifty200] %(message)s")
log = logging.getLogger("load_nifty200")

DATA_FILE = Path(__file__).parent / "data" / "nifty200.csv"
INDEX_CODE = "NIFTY200"
# Fixed effective_from (matches the bootstrap seed) so open membership is stable across re-runs.
EFFECTIVE_FROM = date(2024, 1, 1)


@dataclass(frozen=True, slots=True)
class ConstituentRow:
    symbol: str
    company_name: str
    sector: str
    isin: str


def parse_nifty200_csv(text_content: str) -> list[ConstituentRow]:
    """Parse the NSE ``ind_nifty200list.csv`` (Company Name, Industry, Symbol, Series, ISIN Code)
    into typed rows. Skips blank/symbol-less lines. Pure — no I/O."""
    reader = csv.DictReader(io.StringIO(text_content))
    rows: list[ConstituentRow] = []
    for record in reader:
        symbol = (record.get("Symbol") or "").strip()
        if not symbol:
            continue
        rows.append(
            ConstituentRow(
                symbol=symbol,
                company_name=(record.get("Company Name") or "").strip(),
                sector=(record.get("Industry") or "").strip(),
                isin=(record.get("ISIN Code") or "").strip(),
            )
        )
    return rows


_UPSERT_STOCK_SQL = text(
    """
    INSERT INTO stocks (market_id, symbol, isin, company_name, sector, is_active)
    SELECT m.id, :symbol, :isin, :company_name, :sector, true
    FROM markets m WHERE m.code = :market
    ON CONFLICT (market_id, symbol) DO UPDATE
        SET isin         = EXCLUDED.isin,
            company_name = EXCLUDED.company_name,
            sector       = EXCLUDED.sector,
            is_active    = true
    """
)
# Open membership guarded by NOT EXISTS (no unique key on the open row) — idempotent like the seed.
_INSERT_MEMBERSHIP_SQL = text(
    """
    INSERT INTO index_constituents (index_code, stock_id, effective_from, effective_to)
    SELECT :index_code, s.id, :effective_from, NULL
    FROM stocks s
    JOIN markets m ON m.id = s.market_id AND m.code = :market
    WHERE s.symbol = ANY(:symbols)
      AND NOT EXISTS (
          SELECT 1 FROM index_constituents ic
          WHERE ic.index_code = :index_code AND ic.stock_id = s.id AND ic.effective_to IS NULL
      )
    RETURNING stock_id
    """
)


def load_universe(session: Session, rows: list[ConstituentRow], market: str) -> tuple[int, int]:
    """Upsert stocks + open NIFTY200 membership; returns (stocks_upserted, memberships_added)."""
    for row in rows:
        session.execute(
            _UPSERT_STOCK_SQL,
            {
                "market": market,
                "symbol": row.symbol,
                "isin": row.isin or None,
                "company_name": row.company_name,
                "sector": row.sector or None,
            },
        )
    added = session.execute(
        _INSERT_MEMBERSHIP_SQL,
        {
            "index_code": INDEX_CODE,
            "effective_from": EFFECTIVE_FROM,
            "market": market,
            "symbols": [r.symbol for r in rows],
        },
    ).all()
    return len(rows), len(added)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the full Nifty 200 into the dev universe.")
    parser.add_argument("--market", default="NSE")
    args = parser.parse_args()

    rows = parse_nifty200_csv(DATA_FILE.read_text(encoding="utf-8"))
    log.info("parsed %d constituents from %s", len(rows), DATA_FILE.name)
    with privileged_session_scope() as session:
        stocks, added = load_universe(session, rows, args.market)
    log.info("upserted %d stocks; added %d new open %s memberships", stocks, added, INDEX_CODE)


if __name__ == "__main__":
    main()

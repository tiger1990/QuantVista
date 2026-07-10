"""Dev-only backfill: populate scores for the NSE dev universe.

Runs the real pipeline (yfinance prices -> indicators -> factors -> scores) against the dev DB so
``/rankings`` and the dashboard render real numbers.

HONEST CEILING: dev data (Yahoo, no fundamentals) yields PARTIAL-coverage scores -- momentum + risk
only; no fundamental/quality signal until the licensed market-data vendor (QV-072). NOT for
production. Idempotent (per-``(stock, date)`` upserts + run keys), safe to re-run.

By default the price step runs the STRICT job (``backfill_daily_prices`` -- any stock failing
aborts). ``--tolerant`` (QV-092, for the full Nifty 200) instead calls ``PriceIngestionService``
directly: transient Yahoo 429s / delisted tickers are logged per-stock and the run proceeds over the
names that loaded. Production STRICT is untouched.

Usage (from ``backend/`` with the venv active)::

    python scripts/dev_backfill.py [--days 400] [--market NSE] [--tolerant]
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from quantvista.core.events import get_event_bus
from quantvista.jobs.compute import compute_indicators
from quantvista.jobs.ingest import backfill_daily_prices
from quantvista.jobs.scoring import compute_factors, compute_scores
from quantvista.market_data.adapters.yfinance_dev import YFinanceDevProvider, yahoo_symbol
from quantvista.market_data.services import PriceIngestionService
from quantvista.market_data.trading_calendar import last_completed_session

logging.basicConfig(level=logging.INFO, format="[dev_backfill] %(message)s")
log = logging.getLogger("dev_backfill")


def _backfill_prices_tolerant(market: str, start: date, end: date) -> None:
    """Load prices with per-stock isolation (no STRICT abort) -- for the full Nifty 200 (QV-092)."""
    service = PriceIngestionService(
        YFinanceDevProvider(), get_event_bus(), symbol_mapper=yahoo_symbol
    )
    report = service.ingest(market, start, end, index_code="NIFTY200")
    log.info(
        "  prices (tolerant): %d/%d ok, %d no-data, %d failed, %d rows",
        report.stocks_ok,
        report.stocks_total,
        report.stocks_no_data,
        report.stocks_failed,
        report.rows_upserted,
    )
    for symbol, err in report.failures[:20]:
        log.warning("  dropped %s: %s", symbol, err[:120])


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate dev scores for the NSE universe.")
    parser.add_argument("--days", type=int, default=400, help="days of price history to backfill")
    parser.add_argument("--market", default="NSE")
    parser.add_argument(
        "--tolerant",
        action="store_true",
        help="per-stock isolation for the price load (full Nifty 200; QV-092)",
    )
    args = parser.parse_args()

    target = last_completed_session(date.today())
    start = target - timedelta(days=args.days)
    tiso = target.isoformat()

    log.info("prices %s..%s (%s)", start, target, args.market)
    if args.tolerant:
        _backfill_prices_tolerant(args.market, start, target)
    else:
        prices = backfill_daily_prices(args.market, start=start, end=target)
        log.info("  prices: %s", prices.status.value)
    log.info("indicators %s: %s", tiso, compute_indicators(args.market, tiso))
    log.info("factors    %s: %s", tiso, compute_factors(args.market, tiso))
    log.info("scores     %s: %s", tiso, compute_scores(args.market, tiso))
    log.info("done -- /rankings?market=%s should now return rows for %s", args.market, tiso)


if __name__ == "__main__":
    main()

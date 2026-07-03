"""market_data — daily price ingestion service (QV-016).

Pulls EOD OHLCV for the active index universe through the ``IMarketDataProvider`` seam and
upserts it into ``daily_prices`` (idempotent on ``(stock_id, date)``). Provider-agnostic: it
imports **no** yfinance/pandas and takes an injected provider + event bus + symbol mapper, so
swapping vendors (TrueData/broker) is a new adapter with zero change here (rule #8).

Per-stock isolation: one symbol's failure never sinks the run — an empty result is *no data*
(not an error), an unexpected exception is a *failure*. The caller applies the strict policy
(any failure → fail the job → retry). A ``PricesIngested`` event is emitted per run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

import structlog

from quantvista.core.db import privileged_session_scope
from quantvista.core.interfaces import IEventBus
from quantvista.market_data.interfaces import IMarketDataProvider
from quantvista.market_data.models import PriceBar
from quantvista.market_data.repositories import active_universe, upsert_daily_prices

# (symbol, market) -> provider symbol. Default is identity; the job wires the provider's mapper
# (e.g. yfinance's yahoo_symbol) so the service never depends on a concrete adapter.
SymbolMapper = Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class IngestReport:
    market: str
    start: date
    end: date
    stocks_total: int
    stocks_ok: int
    stocks_no_data: int
    stocks_failed: int
    rows_upserted: int
    failures: list[tuple[str, str]] = field(default_factory=list)


def _identity_mapper(symbol: str, _market: str) -> str:
    return symbol


class PriceIngestionService:
    def __init__(
        self,
        provider: IMarketDataProvider,
        event_bus: IEventBus,
        *,
        symbol_mapper: SymbolMapper = _identity_mapper,
    ) -> None:
        self._provider = provider
        self._events = event_bus
        self._map = symbol_mapper
        self._log = structlog.get_logger()

    def ingest(
        self, market: str, start: date, end: date, *, index_code: str = "NIFTY200"
    ) -> IngestReport:
        """Ingest OHLCV for every open constituent of ``index_code`` over ``[start, end]``."""
        with privileged_session_scope() as session:
            universe = active_universe(session, index_code, market)

        ok = no_data = failed = rows = 0
        failures: list[tuple[str, str]] = []
        for stock in universe:
            try:
                provider_symbol = self._map(stock.symbol, stock.market)
                bars: Sequence[PriceBar] = self._provider.get_prices(
                    provider_symbol, start, end, "1d"
                )
                if not bars:
                    no_data += 1
                    continue
                with privileged_session_scope() as session:
                    rows += upsert_daily_prices(session, stock.stock_id, bars)
                ok += 1
            except Exception as exc:  # per-stock isolation — record and keep going
                failed += 1
                failures.append((stock.symbol, str(exc)))
                self._log.warning("stock_ingest_failed", symbol=stock.symbol, error=str(exc))

        report = IngestReport(
            market, start, end, len(universe), ok, no_data, failed, rows, failures
        )
        self._events.publish(
            "PricesIngested",
            {
                "market": market,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "stocks_ok": ok,
                "rows_upserted": rows,
            },
        )
        return report

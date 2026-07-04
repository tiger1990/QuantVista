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
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

import structlog

from quantvista.core.db import privileged_session_scope
from quantvista.core.interfaces import IEventBus
from quantvista.market_data.fundamentals import record_fundamental_version
from quantvista.market_data.interfaces import IMarketDataProvider
from quantvista.market_data.macro import IMacroProvider, MacroSeries
from quantvista.market_data.models import (
    CorporateAction,
    FundamentalSnapshot,
    PriceBar,
    ShareholdingSnapshot,
    UniverseEntry,
)
from quantvista.market_data.quality import (
    GateViolation,
    QualityThresholds,
    evaluate_quality,
)
from quantvista.market_data.repositories import (
    active_universe,
    price_quality_metrics,
    recompute_adjusted_close,
    reconcile_constituents,
    upsert_corporate_actions,
    upsert_daily_prices,
    upsert_macro_series,
    upsert_shareholding,
    upsert_stocks,
)
from quantvista.market_data.trading_calendar import sessions_in_range

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


@dataclass(frozen=True, slots=True)
class CorpActionReport:
    market: str
    start: date
    end: date
    stocks_total: int
    stocks_ok: int  # stocks with >=1 action ingested
    stocks_no_data: int  # stocks with no actions in the window (the norm — not an error)
    stocks_failed: int
    actions_upserted: int
    stocks_adjusted: int  # stocks whose adj_close recompute touched >=1 price row
    failures: list[tuple[str, str]] = field(default_factory=list)


class CorporateActionIngestionService:
    """Ingest splits/bonuses/dividends and recompute split/bonus-adjusted ``adj_close`` (QV-017).

    Same provider-agnostic, per-stock-isolated shape as ``PriceIngestionService``. Dividends are
    stored but never applied to ``adj_close`` (``03`` §5 — split/bonus adjustment only).
    """

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
    ) -> CorpActionReport:
        with privileged_session_scope() as session:
            universe = active_universe(session, index_code, market)

        ok = no_data = failed = actions = adjusted = 0
        failures: list[tuple[str, str]] = []
        for stock in universe:
            try:
                provider_symbol = self._map(stock.symbol, stock.market)
                acts: Sequence[CorporateAction] = self._provider.get_corporate_actions(
                    provider_symbol, start, end
                )
                with privileged_session_scope() as session:
                    n = upsert_corporate_actions(session, stock.stock_id, acts)
                    # Recompute adj_close from raw close + all split/bonus rows (idempotent;
                    # reflects late actions across the full history).
                    touched = recompute_adjusted_close(session, stock.stock_id)
                actions += n
                ok += 1 if n else 0
                no_data += 0 if n else 1
                adjusted += 1 if touched else 0
            except Exception as exc:  # per-stock isolation
                failed += 1
                failures.append((stock.symbol, str(exc)))
                self._log.warning("corpaction_ingest_failed", symbol=stock.symbol, error=str(exc))

        report = CorpActionReport(
            market, start, end, len(universe), ok, no_data, failed, actions, adjusted, failures
        )
        self._events.publish(
            "CorpActionsUpdated",
            {
                "market": market,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "actions_upserted": actions,
                "stocks_adjusted": adjusted,
            },
        )
        return report


@dataclass(frozen=True, slots=True)
class ValidationReport:
    market: str
    start: date
    end: date
    passed: bool
    stocks_validated: int  # distinct stocks with data (== metrics.stocks_with_data)
    expected_stocks: int
    violations: list[GateViolation] = field(default_factory=list)


class DataQualityService:
    """Post-ingestion data-quality gates over ``daily_prices`` (QV-018, ``06`` §5).

    A *guard*, not a mutation: reads the run's prices for the active universe, evaluates the four
    gates, and emits exactly one event — ``PricesValidated`` (the downstream trigger) on pass, or
    ``DataQualityGateFailed`` (the alert seam) on fail. The caller applies the strict policy
    (fail the run so the pipeline halts rather than scoring on bad data).
    """

    def __init__(self, event_bus: IEventBus) -> None:
        self._events = event_bus
        self._log = structlog.get_logger()

    def validate(
        self,
        market: str,
        start: date,
        end: date,
        *,
        index_code: str = "NIFTY200",
        thresholds: QualityThresholds | None = None,
    ) -> ValidationReport:
        """Evaluate the gates over ``[start, end]`` for ``index_code``'s open constituents."""
        thresholds = thresholds or QualityThresholds()
        with privileged_session_scope() as session:
            universe = active_universe(session, index_code, market)
        stock_ids = [s.stock_id for s in universe]
        expected_sessions = len(sessions_in_range(start, end))

        with privileged_session_scope() as session:
            metrics = price_quality_metrics(
                session, stock_ids, start, end, expected_sessions=expected_sessions
            )
        result = evaluate_quality(metrics, thresholds)
        report = ValidationReport(
            market,
            start,
            end,
            result.passed,
            metrics.stocks_with_data,
            metrics.expected_stocks,
            result.violations,
        )

        base = {"market": market, "start": start.isoformat(), "end": end.isoformat()}
        if report.passed:
            self._events.publish(
                "PricesValidated",
                {
                    **base,
                    "stocks_validated": report.stocks_validated,
                    "expected_stocks": report.expected_stocks,
                },
            )
        else:
            self._log.error(
                "data_quality_gate_failed", **base, gates=[v.gate for v in report.violations]
            )
            self._events.publish(
                "DataQualityGateFailed",
                {
                    **base,
                    "violations": [
                        {
                            "gate": v.gate,
                            "observed": v.observed,
                            "threshold": v.threshold,
                            "detail": v.detail,
                        }
                        for v in report.violations
                    ],
                },
            )
        return report


@dataclass(frozen=True, slots=True)
class StockMasterReport:
    market: str
    provider_count: int
    inserted: int
    updated: int


@dataclass(frozen=True, slots=True)
class ConstituentsReport:
    index_code: str
    market: str
    as_of: date
    provider_count: int
    added: int
    closed: int
    unchanged: int
    unresolved: list[str] = field(default_factory=list)


class UniverseSyncService:
    """Keep the security master + index membership current (QV-019, ``06`` §2).

    Provider-agnostic (reads the QV-012 ``list_universe`` seam; imports no yfinance). Master sync is
    an upsert (never delists); constituent sync is a survivorship-free PIT reconcile. An unresolved
    provider symbol means the master hasn't caught up — the caller fails the run rather than let an
    incomplete provider view close a real member.
    """

    def __init__(self, provider: IMarketDataProvider, event_bus: IEventBus) -> None:
        self._provider = provider
        self._events = event_bus
        self._log = structlog.get_logger()

    def sync_stock_master(self, market: str, *, index_code: str = "NIFTY200") -> StockMasterReport:
        entries: Sequence[UniverseEntry] = self._provider.list_universe(index_code)
        with privileged_session_scope() as session:
            inserted, updated = upsert_stocks(session, market, entries)
        report = StockMasterReport(market, len(entries), inserted, updated)
        self._events.publish(
            "StockMasterUpdated",
            {"market": market, "inserted": inserted, "updated": updated, "total": len(entries)},
        )
        return report

    def sync_index_constituents(
        self, index_code: str, market: str, as_of: date
    ) -> ConstituentsReport:
        entries: Sequence[UniverseEntry] = self._provider.list_universe(index_code)
        members = [(e.symbol, e.weight) for e in entries]
        with privileged_session_scope() as session:
            counts = reconcile_constituents(session, index_code, market, members, as_of)
        report = ConstituentsReport(
            index_code,
            market,
            as_of,
            len(members),
            counts.added,
            counts.closed,
            counts.unchanged,
            counts.unresolved,
        )
        if counts.unresolved:  # nothing was mutated — surface it, don't announce a sync
            self._log.error(
                "constituents_unresolved",
                index_code=index_code,
                market=market,
                unresolved=counts.unresolved,
            )
        else:
            self._events.publish(
                "ConstituentsUpdated",
                {
                    "index_code": index_code,
                    "market": market,
                    "as_of": as_of.isoformat(),
                    "added": counts.added,
                    "closed": counts.closed,
                    "unchanged": counts.unchanged,
                },
            )
        return report


@dataclass(frozen=True, slots=True)
class FundamentalsReport:
    market: str
    stocks_total: int
    stocks_ok: int  # stocks with >=1 filing recorded
    stocks_no_data: int  # no filing with a period_end (the norm for the dev ttm stub)
    stocks_failed: int
    filings_inserted: int
    filings_revised: int
    filings_unchanged: int
    failures: list[tuple[str, str]] = field(default_factory=list)


# The 6 measures the QV-012 DTO carries → QV-021 ratio-allowlist columns (rest stay NULL).
_SNAPSHOT_RATIOS = ("pe", "forward_pe", "pb", "roe", "roce", "debt_equity")


class FundamentalsIngestionService:
    """Ingest fundamentals through the QV-021 bitemporal primitive (QV-022, ``06`` §5).

    Provider-agnostic + per-stock isolated, like the price/corp-action services. Each
    ``FundamentalSnapshot`` with a non-null ``period_end`` is a filing → the QV-021
    ``record_fundamental_version`` (inserted/revised/unchanged); a ``period_end=None`` snapshot (the
    dev ttm stub) is skipped. All filings in a run share one ``knowledge_time``. Emits
    ``FundamentalsUpdated``.
    """

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
        self,
        market: str,
        *,
        index_code: str = "NIFTY200",
        knowledge_time: datetime | None = None,
    ) -> FundamentalsReport:
        """Ingest the latest filings for every open constituent of ``index_code``."""
        kt = knowledge_time or datetime.now(UTC)
        with privileged_session_scope() as session:
            universe = active_universe(session, index_code, market)

        ok = no_data = failed = inserted = revised = unchanged = 0
        failures: list[tuple[str, str]] = []
        for stock in universe:
            try:
                provider_symbol = self._map(stock.symbol, stock.market)
                snapshots: Sequence[FundamentalSnapshot] = self._provider.get_fundamentals(
                    provider_symbol
                )
                filings = [s for s in snapshots if s.period_end is not None]
                if not filings:
                    no_data += 1
                    continue
                with privileged_session_scope() as session:
                    for snap in filings:
                        assert snap.period_end is not None  # filtered above; narrows for mypy
                        action = record_fundamental_version(
                            session,
                            stock.stock_id,
                            snap.period_end,
                            snap.statement_type or "quarterly",
                            {c: getattr(snap, c) for c in _SNAPSHOT_RATIOS},
                            knowledge_time=kt,
                        )
                        inserted += action == "inserted"
                        revised += action == "revised"
                        unchanged += action == "unchanged"
                ok += 1
            except Exception as exc:  # per-stock isolation
                failed += 1
                failures.append((stock.symbol, str(exc)))
                self._log.warning("fundamentals_ingest_failed", symbol=stock.symbol, error=str(exc))

        report = FundamentalsReport(
            market, len(universe), ok, no_data, failed, inserted, revised, unchanged, failures
        )
        self._events.publish(
            "FundamentalsUpdated",
            {
                "market": market,
                "knowledge_time": kt.isoformat(),
                "inserted": inserted,
                "revised": revised,
                "unchanged": unchanged,
            },
        )
        return report


@dataclass(frozen=True, slots=True)
class ShareholdingReport:
    market: str
    stocks_total: int
    stocks_ok: int  # stocks with >=1 ownership row upserted
    stocks_no_data: int  # no snapshot (the norm — Yahoo shareholding is sparse for India)
    stocks_failed: int
    rows_upserted: int
    failures: list[tuple[str, str]] = field(default_factory=list)


class ShareholdingIngestionService:
    """Ingest PIT-by-date ownership snapshots (QV-023, ``06`` §2).

    Provider-agnostic + per-stock isolated, like the sibling ingest services — but with **no event**
    (the ``06`` job catalog emits none for shareholding). Persistence is a plain upsert keyed
    ``(stock_id, as_of_date)``: re-polling a quarter updates in place, a new quarter is a new row.
    """

    def __init__(
        self,
        provider: IMarketDataProvider,
        *,
        symbol_mapper: SymbolMapper = _identity_mapper,
    ) -> None:
        self._provider = provider
        self._map = symbol_mapper
        self._log = structlog.get_logger()

    def ingest(self, market: str, *, index_code: str = "NIFTY200") -> ShareholdingReport:
        """Upsert the latest ownership snapshots for every open constituent of ``index_code``."""
        with privileged_session_scope() as session:
            universe = active_universe(session, index_code, market)

        ok = no_data = failed = rows = 0
        failures: list[tuple[str, str]] = []
        for stock in universe:
            try:
                provider_symbol = self._map(stock.symbol, stock.market)
                snapshots: Sequence[ShareholdingSnapshot] = self._provider.get_shareholding(
                    provider_symbol
                )
                if not snapshots:
                    no_data += 1
                    continue
                with privileged_session_scope() as session:
                    rows += upsert_shareholding(session, stock.stock_id, snapshots)
                ok += 1
            except Exception as exc:  # per-stock isolation
                failed += 1
                failures.append((stock.symbol, str(exc)))
                self._log.warning("shareholding_ingest_failed", symbol=stock.symbol, error=str(exc))

        return ShareholdingReport(market, len(universe), ok, no_data, failed, rows, failures)


@dataclass(frozen=True, slots=True)
class MacroSyncReport:
    series_code: str  # the CANONICAL key stored (provider-stable)
    start: date
    end: date
    observations_upserted: int


class MacroSyncService:
    """Sync a macro series through the generic provider seam (QV-026), storing the CANONICAL key.

    The provider resolves the canonical ``MacroSeries`` to its own code + fetches; the service
    re-stamps the canonical ``series_code`` before upsert so the persisted key is provider-stable.
    No event (the ``06`` catalog emits none for macro).
    """

    def __init__(self, provider: IMacroProvider) -> None:
        self._provider = provider
        self._log = structlog.get_logger()

    def sync(self, series: MacroSeries, start: date, end: date) -> MacroSyncReport:
        observations = self._provider.get_series(self._provider.code_for(series), start, end)
        canonical = [replace(o, series_code=series.value) for o in observations]
        with privileged_session_scope() as session:
            written = upsert_macro_series(session, canonical)
        return MacroSyncReport(series.value, start, end, written)

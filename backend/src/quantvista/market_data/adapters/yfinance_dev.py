"""Internal-only dev adapter over yfinance (QV-012).

Implements ``IMarketDataProvider`` by mapping Yahoo Finance responses into our vendor-neutral
DTOs. **Licensing guardrail (project rule #8, ``plans/03`` §1):** yfinance/Yahoo is allowed for
internal dev ONLY — never behind a paying tier — so every DTO is hard-stamped
``license_class=NON_COMMERCIAL_DEV``. yfinance is an optional ``dev-data`` extra and is imported
lazily; the ticker factory is injectable so tests never touch the network. Yahoo fields are
unreliable/sparse by design — missing/NaN values degrade to ``None`` rather than raising. All
numerics are converted via ``Decimal(str(...))`` (never ``float`` → project money rule).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from quantvista.market_data.models import (
    CorporateAction,
    CorporateActionType,
    FundamentalSnapshot,
    LicenseClass,
    PriceBar,
    Provenance,
    ShareholdingSnapshot,
    UniverseEntry,
)
from quantvista.market_data.ratios import StatementBundle, compute

_SOURCE = "yfinance"

# yfinance line-item names vary — first match wins, else that input is None (→ ratio None).
_LINE_ITEMS: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "ebit": ("EBIT", "Operating Income"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "operating_income": ("Operating Income", "Total Operating Income As Reported"),
    "net_income": (
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income Continuous Operations",
    ),
    "pretax_income": ("Pretax Income", "Pre Tax Income"),
    "tax_provision": ("Tax Provision", "Income Tax Expense"),
    "total_assets": ("Total Assets",),
    "current_assets": ("Current Assets", "Total Current Assets"),
    "current_liabilities": ("Current Liabilities", "Total Current Liabilities"),
    "inventory": ("Inventory",),
    "total_debt": ("Total Debt",),
    "cash": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
    "equity": (
        "Stockholders Equity",
        "Common Stock Equity",
        "Total Equity Gross Minority Interest",
    ),
    "shares": ("Ordinary Shares Number", "Share Issued"),
    "operating_cash_flow": (
        "Operating Cash Flow",
        "Cash Flow From Continuing Operating Activities",
    ),
    "capex": ("Capital Expenditure", "Capital Expenditure Reported"),
}
_FILING_LAG_DAYS = 45  # Indian norm: results filed ~6 weeks after fiscal period-end

# Representative dev universe (symbol → name). NOT the authoritative NIFTY200 — the real
# point-in-time constituent sync is QV-019; this is enough to exercise the pipeline in dev.
_DEV_UNIVERSE: dict[str, str] = {
    "RELIANCE.NS": "Reliance Industries",
    "TCS.NS": "Tata Consultancy Services",
    "INFY.NS": "Infosys",
    "HDFCBANK.NS": "HDFC Bank",
    "ICICIBANK.NS": "ICICI Bank",
}

TickerFactory = Callable[[str], Any]

# Yahoo Finance exchange suffixes by our canonical market code. The DB stores the plain
# ticker (RELIANCE); Yahoo needs the suffixed form (RELIANCE.NS). Each provider owns its own
# mapping — a future TrueData adapter has its own, the ingestion service stays symbol-agnostic.
_YAHOO_SUFFIX: dict[str, str] = {"NSE": ".NS", "BSE": ".BO"}


def yahoo_symbol(symbol: str, market_code: str) -> str:
    """Map a canonical ``(symbol, market)`` to the Yahoo ticker (RELIANCE, NSE → RELIANCE.NS)."""
    return f"{symbol}{_YAHOO_SUFFIX.get(market_code, '')}"


def _canonical(yahoo_ticker: str) -> str:
    """Strip this adapter's Yahoo suffix to recover the canonical symbol (RELIANCE.NS→RELIANCE)."""
    for suffix in _YAHOO_SUFFIX.values():
        if yahoo_ticker.endswith(suffix):
            return yahoo_ticker[: -len(suffix)]
    return yahoo_ticker


def _default_ticker_factory(symbol: str) -> Any:
    """Lazily construct a ``yfinance.Ticker`` (clear error if the extra isn't installed)."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "yfinance is not installed. It is an internal-only dev dependency — "
            "install it with `pip install -e .[dev-data]`."
        ) from exc
    return yf.Ticker(symbol)


def _dec(value: Any) -> Decimal | None:
    """Convert an upstream numeric to ``Decimal`` via ``str``; NaN/None/garbage → ``None``."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return None if result.is_nan() else result


def _int(value: Any) -> int | None:
    d = _dec(value)
    return int(d) if d is not None else None


def _safe_div(numer: Decimal | None, denom: Decimal | None) -> Decimal | None:
    if numer is None or denom is None or denom == 0:
        return None
    try:
        return numer / denom
    except (InvalidOperation, ArithmeticError):
        return None


def _cell(df: Any, key: str, col: Any) -> Decimal | None:
    """First matching line item for ``key`` at period ``col`` in a yfinance statement DataFrame."""
    if df is None or col is None or getattr(df, "empty", True):
        return None
    for name in _LINE_ITEMS[key]:
        if name in df.index:
            try:
                return _dec(df.loc[name, col])
            except (KeyError, TypeError):
                continue
    return None


def _eps(inc: Any, bs: Any, col: Any, info_shares: Decimal | None) -> Decimal | None:
    return _safe_div(_cell(inc, "net_income", col), _cell(bs, "shares", col) or info_shares)


def _fcf(cf: Any, col: Any) -> Decimal | None:
    ocf, capex = _cell(cf, "operating_cash_flow", col), _cell(cf, "capex", col)
    return None if ocf is None or capex is None else ocf - abs(capex)


class YFinanceDevProvider:
    """``IMarketDataProvider`` backed by Yahoo Finance — internal dev use only."""

    def __init__(self, ticker_factory: TickerFactory | None = None) -> None:
        self._ticker = ticker_factory or _default_ticker_factory

    def _provenance(self, symbol: str) -> Provenance:
        return Provenance(
            source=_SOURCE,
            source_url=f"https://finance.yahoo.com/quote/{symbol}",
            license_class=LicenseClass.NON_COMMERCIAL_DEV,
        )

    def get_prices(
        self, symbol: str, start: date, end: date, interval: str = "1d"
    ) -> Sequence[PriceBar]:
        if interval != "1d":
            raise ValueError(
                f"YFinanceDevProvider supports only interval='1d' (got {interval!r}); "
                "intraday is a separate concern (see market-data-provider-strategy)."
            )
        prov = self._provenance(symbol)
        # yfinance treats `end` as EXCLUSIVE — add a day so our contract's `end` is inclusive
        # (a single-session fetch start==end must return that session). auto_adjust=False keeps
        # raw close and Adj Close distinct (adjustment is QV-017).
        history = self._ticker(symbol).history(
            start=start, end=end + timedelta(days=1), auto_adjust=False
        )
        if getattr(history, "empty", False):
            return []
        bars: list[PriceBar] = []
        for index, row in history.iterrows():
            bar_date = index.date()
            if bar_date > end:  # defensive: never return a bar past the requested end
                continue
            close = _dec(row.get("Close"))
            if close is None:
                # yfinance often returns the latest/unsettled session with a NaN close (OHLCV
                # partially populated). Persisting it as a null-close row breaks rankings (which
                # read `close`) and every adj_close-derived indicator (momentum/risk). Skip the
                # incomplete bar — the last *settled* session stays the newest usable one.
                continue
            bars.append(
                PriceBar(
                    symbol=symbol,
                    date=bar_date,
                    open=_dec(row.get("Open")),
                    high=_dec(row.get("High")),
                    low=_dec(row.get("Low")),
                    close=close,
                    adj_close=_dec(row.get("Adj Close")),
                    volume=_int(row.get("Volume")),
                    provenance=prov,
                )
            )
        return bars

    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        prov = self._provenance(symbol)
        actions = self._ticker(symbol).actions
        if getattr(actions, "empty", False):
            return []
        out: list[CorporateAction] = []
        for index, row in actions.iterrows():
            ex_date = index.date()
            if not (start <= ex_date <= end):
                continue
            dividend = _dec(row.get("Dividends"))
            split = _dec(row.get("Stock Splits"))
            if dividend is not None and dividend > 0:
                out.append(
                    CorporateAction(
                        symbol=symbol,
                        ex_date=ex_date,
                        action_type=CorporateActionType.DIVIDEND,
                        ratio_or_amount=dividend,
                        details={},
                        provenance=prov,
                    )
                )
            if split is not None and split > 0:
                out.append(
                    CorporateAction(
                        symbol=symbol,
                        ex_date=ex_date,
                        action_type=CorporateActionType.SPLIT,
                        ratio_or_amount=split,
                        details={},
                        provenance=prov,
                    )
                )
        return out

    def get_fundamentals(self, symbol: str) -> Sequence[FundamentalSnapshot]:
        """Dated ratios per annual fiscal period from the financial statements (QV-095).

        Computes statement-intrinsic ratios from ``income_stmt``/``balance_sheet``/``cashflow``
        (real ``period_end`` → passes the bitemporal store, unlike the old ``.info`` TTM stub);
        valuation ratios (PE/PB/EV…) are added to the latest period only, from the current price.
        """
        ticker = self._ticker(symbol)
        inc = getattr(ticker, "income_stmt", None)
        bs = getattr(ticker, "balance_sheet", None)
        cf = getattr(ticker, "cashflow", None)
        if inc is None or getattr(inc, "empty", True):
            return []

        info = getattr(ticker, "info", None) or {}
        info_shares = _dec(info.get("sharesOutstanding"))
        price = _dec(info.get("regularMarketPrice") or info.get("currentPrice"))
        forward_eps = _dec(info.get("forwardEps"))
        prov = self._provenance(symbol)

        periods = list(inc.columns)  # period-end timestamps, newest first
        snapshots: list[FundamentalSnapshot] = []
        valuation_done = False  # valuation goes on the latest period that actually has data
        for i, col in enumerate(periods):
            revenue = _cell(inc, "revenue", col)
            net_income = _cell(inc, "net_income", col)
            equity = _cell(bs, "equity", col)
            # yfinance sometimes carries an empty trailing column (a fiscal-year change, or a
            # not-yet-reported year — e.g. NESTLEIND). Skip it rather than storing an all-None row
            # that would shadow the latest REAL period in stock-detail/screener/scoring.
            if revenue is None and net_income is None and equity is None:
                continue
            apply_valuation = not valuation_done
            valuation_done = True
            prior = periods[i + 1] if i + 1 < len(periods) else None
            bundle = StatementBundle(
                revenue=revenue,
                ebit=_cell(inc, "ebit", col),
                ebitda=_cell(inc, "ebitda", col),
                operating_income=_cell(inc, "operating_income", col),
                net_income=net_income,
                tax_rate=_safe_div(
                    _cell(inc, "tax_provision", col), _cell(inc, "pretax_income", col)
                ),
                total_assets=_cell(bs, "total_assets", col),
                current_assets=_cell(bs, "current_assets", col),
                current_liabilities=_cell(bs, "current_liabilities", col),
                inventory=_cell(bs, "inventory", col),
                total_debt=_cell(bs, "total_debt", col),
                cash=_cell(bs, "cash", col),
                equity=equity,
                shares=_cell(bs, "shares", col) or info_shares,
                operating_cash_flow=_cell(cf, "operating_cash_flow", col),
                capex=_cell(cf, "capex", col),
                prior_revenue=_cell(inc, "revenue", prior) if prior is not None else None,
                prior_eps=_eps(inc, bs, prior, info_shares) if prior is not None else None,
                prior_fcf=_fcf(cf, prior) if prior is not None else None,
                price=price if apply_valuation else None,
                forward_eps=forward_eps if apply_valuation else None,
            )
            snapshots.append(
                FundamentalSnapshot(
                    symbol=symbol,
                    period_end=col.date(),
                    statement_type="annual",
                    provenance=prov,
                    **compute(bundle),  # keys match the DTO's ratio fields exactly
                )
            )
        return snapshots

    def get_shareholding(self, symbol: str) -> Sequence[ShareholdingSnapshot]:
        info = getattr(self._ticker(symbol), "info", None) or {}
        insiders = _dec(info.get("heldPercentInsiders"))
        institutions = _dec(info.get("heldPercentInstitutions"))
        if insiders is None and institutions is None:
            return []  # best-effort: Yahoo shareholding is sparse for India
        hundred = Decimal(100)
        return [
            ShareholdingSnapshot(
                symbol=symbol,
                as_of_date=date.today(),
                promoter_holding=insiders * hundred if insiders is not None else None,
                fii_holding=None,  # Yahoo does not split FII/DII
                dii_holding=None,
                public_holding=None,
                pledged_pct=None,
                provenance=self._provenance(symbol),
            )
        ]

    def list_universe(self, index_code: str = "NIFTY200") -> Sequence[UniverseEntry]:
        """NON-AUTHORITATIVE dev universe — a 5-symbol convenience list, not the real NIFTY200.

        Emits the **canonical** symbol (``RELIANCE``, venue in ``exchange``) so it maps 1:1 to
        ``stocks.symbol``; the Yahoo suffix is this adapter's private concern. ``weight`` is
        ``None`` (Yahoo has no index weights). The authoritative membership + weights arrive with
        the licensed vendor (QV-072) — this list must never drive a production constituent sync.
        """
        return [
            UniverseEntry(
                symbol=_canonical(yahoo_ticker),
                name=name,
                isin=None,
                exchange="NSE",
                is_active=True,
                provenance=self._provenance(yahoo_ticker),
                weight=None,
            )
            for yahoo_ticker, name in _DEV_UNIVERSE.items()
        ]

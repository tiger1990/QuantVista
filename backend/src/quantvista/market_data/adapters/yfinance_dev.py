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
from datetime import date
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

_SOURCE = "yfinance"

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

    def get_prices(self, symbol: str, start: date, end: date) -> Sequence[PriceBar]:
        prov = self._provenance(symbol)
        # auto_adjust=False keeps raw close and Adj Close distinct (adjustment is QV-017).
        history = self._ticker(symbol).history(start=start, end=end, auto_adjust=False)
        if getattr(history, "empty", False):
            return []
        bars: list[PriceBar] = []
        for index, row in history.iterrows():
            bars.append(
                PriceBar(
                    symbol=symbol,
                    date=index.date(),
                    open=_dec(row.get("Open")),
                    high=_dec(row.get("High")),
                    low=_dec(row.get("Low")),
                    close=_dec(row.get("Close")),
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
        info = getattr(self._ticker(symbol), "info", None) or {}
        return [
            FundamentalSnapshot(
                symbol=symbol,
                period_end=None,
                statement_type="ttm",
                pe=_dec(info.get("trailingPE")),
                forward_pe=_dec(info.get("forwardPE")),
                pb=_dec(info.get("priceToBook")),
                roe=_dec(info.get("returnOnEquity")),
                roce=None,  # not exposed by yfinance
                debt_equity=_dec(info.get("debtToEquity")),
                provenance=self._provenance(symbol),
            )
        ]

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
        return [
            UniverseEntry(
                symbol=symbol,
                name=name,
                isin=None,
                exchange="NSE",
                is_active=True,
                provenance=self._provenance(symbol),
            )
            for symbol, name in _DEV_UNIVERSE.items()
        ]

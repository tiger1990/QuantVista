"""Fundamental ratio computation (QV-095) — pure, None-safe, from a normalized statement bundle.

Statement-intrinsic ratios (ROE, ROCE, ROIC, margins, D/E, current/quick, revenue/EPS/FCF + YoY
growth) are period-correct — computed purely from the statements. Valuation ratios (PE, PB, PS, EV,
EV/EBITDA, PEG, forward PE) mix a point-in-time ``price`` with the fundamentals → only meaningful
for the latest period. Any missing input or zero denominator yields ``None`` (never raises).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation

_DEFAULT_TAX_RATE = Decimal("0.25")  # NOPAT fallback when the effective rate isn't available


@dataclass(frozen=True, slots=True)
class StatementBundle:
    """Normalized line items for one fiscal period (+ prior-period figures for growth, + price)."""

    # income statement
    revenue: Decimal | None = None
    ebit: Decimal | None = None
    ebitda: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    tax_rate: Decimal | None = None  # effective rate for NOPAT; else _DEFAULT_TAX_RATE
    # balance sheet
    total_assets: Decimal | None = None
    current_assets: Decimal | None = None
    current_liabilities: Decimal | None = None
    inventory: Decimal | None = None
    total_debt: Decimal | None = None
    cash: Decimal | None = None
    equity: Decimal | None = None
    shares: Decimal | None = None
    # cash flow
    operating_cash_flow: Decimal | None = None
    capex: Decimal | None = None
    # prior period (YoY growth)
    prior_revenue: Decimal | None = None
    prior_eps: Decimal | None = None
    prior_fcf: Decimal | None = None
    # valuation inputs (latest period only)
    price: Decimal | None = None
    forward_eps: Decimal | None = None


def _div(numer: Decimal | None, denom: Decimal | None) -> Decimal | None:
    """Safe division: ``None`` on a missing operand or zero denominator."""
    if numer is None or denom is None or denom == 0:
        return None
    try:
        return numer / denom
    except (InvalidOperation, DivisionByZero):
        return None


def _growth(current: Decimal | None, prior: Decimal | None) -> Decimal | None:
    """YoY growth ``(cur − prior) / |prior|``; ``None`` without both periods or a zero base."""
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def compute(b: StatementBundle) -> dict[str, Decimal | None]:
    """All ratios for one period. Valuation entries are ``None`` unless ``price``/``shares`` set."""
    eps = _div(b.net_income, b.shares)
    fcf = (
        None
        if b.operating_cash_flow is None or b.capex is None
        else b.operating_cash_flow - abs(b.capex)
    )
    cash = b.cash if b.cash is not None else Decimal(0)

    capital_employed = (
        None
        if b.total_assets is None or b.current_liabilities is None
        else b.total_assets - b.current_liabilities
    )
    nopat = (
        None
        if b.ebit is None
        else b.ebit * (1 - (b.tax_rate if b.tax_rate is not None else _DEFAULT_TAX_RATE))
    )
    invested_capital = (
        None if b.total_debt is None or b.equity is None else b.total_debt + b.equity - cash
    )

    market_cap = None if b.price is None or b.shares is None else b.price * b.shares
    ev = None if market_cap is None or b.total_debt is None else market_cap + b.total_debt - cash
    bvps = _div(b.equity, b.shares)
    quick_assets = (
        None if b.current_assets is None else b.current_assets - (b.inventory or Decimal(0))
    )

    ratios: dict[str, Decimal | None] = {
        # statement-intrinsic
        "roe": _div(b.net_income, b.equity),
        "roce": _div(b.ebit, capital_employed),
        "roic": _div(nopat, invested_capital),
        "debt_equity": _div(b.total_debt, b.equity),
        "operating_margin": _div(b.operating_income, b.revenue),
        "net_margin": _div(b.net_income, b.revenue),
        "current_ratio": _div(b.current_assets, b.current_liabilities),
        "quick_ratio": _div(quick_assets, b.current_liabilities),
        "revenue": b.revenue,
        "eps": eps,
        "fcf": fcf,
        "revenue_growth": _growth(b.revenue, b.prior_revenue),
        "eps_growth": _growth(eps, b.prior_eps),
        "fcf_growth": _growth(fcf, b.prior_fcf),
        # valuation (price-dependent; latest period only)
        "pe": _div(b.price, eps),
        "forward_pe": _div(b.price, b.forward_eps),
        "pb": _div(b.price, bvps),
        "price_sales": _div(market_cap, b.revenue),
        "enterprise_value": ev,
        "ev_ebitda": _div(ev, b.ebitda),
    }
    eps_growth = ratios["eps_growth"]
    ratios["peg"] = _div(ratios["pe"], None if eps_growth is None else eps_growth * 100)
    return ratios

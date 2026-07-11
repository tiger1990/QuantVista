"""Unit tests for the pure fundamental-ratio computation (market_data.ratios, QV-095)."""

from __future__ import annotations

from decimal import Decimal

from quantvista.market_data.ratios import StatementBundle, compute

D = Decimal


def _full() -> StatementBundle:
    # A clean, real-shaped annual period (+ prior for growth, + price for valuation).
    return StatementBundle(
        revenue=D(1000),
        ebit=D(200),
        ebitda=D(250),
        operating_income=D(180),
        net_income=D(120),
        tax_rate=D("0.25"),
        total_assets=D(2000),
        current_assets=D(600),
        current_liabilities=D(400),
        inventory=D(150),
        total_debt=D(500),
        cash=D(100),
        equity=D(800),
        shares=D(100),
        operating_cash_flow=D(160),
        capex=D(-60),
        prior_revenue=D(800),
        prior_eps=D("1.00"),
        prior_fcf=D(80),
        price=D(240),
        forward_eps=D("1.50"),
    )


def test_statement_intrinsic_ratios() -> None:
    r = compute(_full())
    assert r["roe"] == D(120) / D(800)  # net_income / equity
    assert r["roce"] == D(200) / (D(2000) - D(400))  # ebit / (assets - current liab)
    assert r["debt_equity"] == D(500) / D(800)
    assert r["operating_margin"] == D(180) / D(1000)
    assert r["net_margin"] == D(120) / D(1000)
    assert r["current_ratio"] == D(600) / D(400)
    assert r["quick_ratio"] == (D(600) - D(150)) / D(400)  # ex-inventory
    assert r["eps"] == D(120) / D(100)  # 1.20
    assert r["fcf"] == D(160) - D(60)  # ocf - |capex| = 100
    # roic = nopat / invested; nopat = ebit*(1-tax)=150; invested = debt+equity-cash=1200
    assert r["roic"] == (D(200) * D("0.75")) / (D(500) + D(800) - D(100))


def test_growth_needs_prior_period() -> None:
    r = compute(_full())
    assert r["revenue_growth"] == (D(1000) - D(800)) / D(800)  # +25%
    assert r["eps_growth"] == (D("1.20") - D("1.00")) / D("1.00")  # +20%
    assert r["fcf_growth"] == (D(100) - D(80)) / D(80)


def test_valuation_ratios() -> None:
    r = compute(_full())
    assert r["pe"] == D(240) / (D(120) / D(100))  # price / eps = 240/1.2 = 200
    assert r["pb"] == D(240) / (D(800) / D(100))  # price / bvps = 240/8 = 30
    assert r["forward_pe"] == D(240) / D("1.50")
    assert r["price_sales"] == (D(240) * D(100)) / D(1000)  # market cap / revenue
    assert r["enterprise_value"] == D(240) * D(100) + D(500) - D(100)  # mcap + debt - cash
    assert r["ev_ebitda"] == r["enterprise_value"] / D(250)
    assert r["peg"] == r["pe"] / (r["eps_growth"] * 100)  # type: ignore[operator]


def test_missing_inputs_yield_none_not_error() -> None:
    r = compute(StatementBundle(revenue=D(1000)))  # almost everything missing
    assert r["roe"] is None and r["roce"] is None and r["pe"] is None
    assert r["revenue"] == D(1000)
    assert r["revenue_growth"] is None  # no prior period


def test_zero_denominator_is_none() -> None:
    r = compute(StatementBundle(net_income=D(50), equity=D(0), shares=D(0)))
    assert r["roe"] is None  # zero equity
    assert r["eps"] is None  # zero shares


def test_valuation_absent_without_price() -> None:
    r = compute(StatementBundle(net_income=D(120), equity=D(800), shares=D(100)))  # no price
    assert r["pe"] is None and r["pb"] is None and r["enterprise_value"] is None
    assert r["roe"] == D(120) / D(800)  # intrinsic still computed

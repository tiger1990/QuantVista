import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { StockDetail } from "@/lib/api/queries";

import { CompareMatrix } from "./CompareMatrix";

function stock(symbol: string, overrides: Partial<StockDetail["snapshot"]>): StockDetail {
  return {
    symbol,
    company_name: `${symbol} Ltd`,
    sector: "Financials",
    industry: null,
    market_cap_bucket: "large",
    market: "NSE",
    is_active: true,
    snapshot: {
      price_date: null,
      close: null,
      composite_score: null,
      fundamental_score: null,
      momentum_score: null,
      quality_score: null,
      sentiment_score: null,
      risk_score: null,
      coverage: null,
      model_version: null,
      weights_version: null,
      pe: null,
      pb: null,
      roe: null,
      roce: null,
      debt_equity: null,
      ...overrides,
    } as StockDetail["snapshot"],
  };
}

describe("CompareMatrix", () => {
  it("renders a column per stock and the score/fundamental rows", () => {
    render(
      <CompareMatrix
        details={[
          stock("RELIANCE", { composite_score: 82.4, pe: 24.1 }),
          stock("TCS", { composite_score: 55, pe: null }),
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: "RELIANCE" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TCS" })).toBeInTheDocument();

    // Composite score row: formatted to one decimal.
    const compositeRow = screen.getByRole("row", { name: /composite/i });
    expect(within(compositeRow).getByText("82.4")).toBeInTheDocument();

    // Missing fundamental renders an em dash, not a crash.
    const peRow = screen.getByRole("row", { name: /p\/e/i });
    expect(within(peRow).getByText("24.10")).toBeInTheDocument();
    expect(within(peRow).getByText("—")).toBeInTheDocument();
  });
});

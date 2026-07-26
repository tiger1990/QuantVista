import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RiskError, type RiskResponse } from "@/lib/api/queries";

import { RiskDashboard } from "./RiskDashboard";

type RiskState = {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  data: RiskResponse | undefined;
};

let state: RiskState;

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useRisk: () => state };
});

const RISK: RiskResponse = {
  as_of_date: "2026-07-20",
  beta: "1.375",
  volatility: "0.1800",
  max_drawdown: "0.1200",
  sharpe: "0.9500",
  sortino: null, // thin downside → null → em dash
  hhi: "0.625",
  sector_exposure: { IT: "0.25", Energy: "0.75" },
  beta_coverage: { covered: 3, total: 4, ratio: "0.75" },
  drawdown_series: [
    { date: "2026-07-18", value: "0" },
    { date: "2026-07-19", value: "-0.12" },
  ],
};

beforeEach(() => {
  state = { isLoading: false, isError: false, error: null, data: RISK };
});

describe("RiskDashboard", () => {
  it("shows a loading state", () => {
    state = { isLoading: true, isError: false, error: null, data: undefined };
    render(<RiskDashboard portfolioId="p" />);
    expect(screen.getByText(/loading risk/i)).toBeInTheDocument();
  });

  it("explains the no-data (422) case", () => {
    state = { isLoading: false, isError: true, error: new RiskError("no_data"), data: undefined };
    render(<RiskDashboard portfolioId="p" />);
    expect(screen.getByText(/add holdings with price history/i)).toBeInTheDocument();
  });

  it("renders metric tiles, em-dash for null, and beta coverage", () => {
    render(<RiskDashboard portfolioId="p" />);
    expect(screen.getByText("1.38")).toBeInTheDocument(); // beta
    expect(screen.getByText("18.00%")).toBeInTheDocument(); // volatility
    expect(screen.getByText("12.00%")).toBeInTheDocument(); // max drawdown
    expect(screen.getByText("—")).toBeInTheDocument(); // sortino null
    expect(screen.getByText(/beta covers 3\/4 holdings/i)).toBeInTheDocument();
    expect(screen.getByText(/research signal, not investment advice/i)).toBeInTheDocument();
  });
});

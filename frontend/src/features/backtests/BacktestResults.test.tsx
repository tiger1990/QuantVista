import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Backtest } from "@/lib/api/queries";

import { BacktestResults } from "./BacktestResults";

const backtest: Backtest = {
  id: "bt-1",
  status: "succeeded",
  spec: {
    rules: { rank_by: "momentum", top_n: 15, rebalance: "monthly" },
    start: "2022-01-01",
    end: "2022-12-31",
  },
  metrics: {
    total_return: "0.2",
    benchmark_return: "0.12",
    excess_return: "0.08",
    cagr: "0.19",
    hit_rate: "0.55",
    ann_vol: "0.15",
    max_drawdown: "-0.1",
    sharpe: "1.2",
    sortino: "1.5",
    beta: "0.9",
    tracking_error: "0.05",
    information_ratio: "0.7",
    avg_turnover: "0.3",
    avg_exposure: "0.95",
    n_rebalances: 12,
    reproducibility_hash: "abcdef0123456789",
    equity_curve: [
      { as_of: "2022-01-01", strategy: "1.0", benchmark: "1.0" },
      { as_of: "2022-06-01", strategy: "1.1", benchmark: "1.05" },
    ],
  },
  result_ref: null,
  error: null,
  created_at: "2022-01-01T00:00:00Z",
  started_at: "2022-01-01T00:00:01Z",
  finished_at: "2022-01-01T00:00:02Z",
};

describe("BacktestResults tearsheet", () => {
  it("headlines the total return and strategy label", () => {
    render(<BacktestResults backtest={backtest} />);
    // total return shows as the masthead headline and in the factsheet — at least one instance.
    expect(screen.getAllByText("20.00%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/momentum · top 15 · monthly/i)).toBeInTheDocument();
    expect(screen.getByText(/2022-01-01 → 2022-12-31/)).toBeInTheDocument();
  });

  it("renders the dense metrics factsheet", () => {
    render(<BacktestResults backtest={backtest} />);
    expect(screen.getByText("Sharpe")).toBeInTheDocument();
    expect(screen.getByText("1.20")).toBeInTheDocument();
    expect(screen.getByText("Sortino")).toBeInTheDocument();
    expect(screen.getByText("Information ratio")).toBeInTheDocument();
  });

  it("closes with a centred, self-contained disclaimer", () => {
    render(<BacktestResults backtest={backtest} />);
    const disclaimer = screen.getByText(/not investment advice/i);
    expect(disclaimer).toBeInTheDocument();
    expect(disclaimer).toHaveTextContent(/past performance does not indicate future results/i);
    expect(disclaimer.className).toMatch(/text-center/);
  });

  it("keeps the reproducibility fingerprint out of the UI", () => {
    // it is an audit artifact, not a user-facing figure; still persisted and served by the API
    render(<BacktestResults backtest={backtest} />);
    expect(screen.queryByText(/abcdef012345/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/recipe/i)).not.toBeInTheDocument();
  });

  it("links to the Methodology page now that it exists (QV-070)", () => {
    // was inverted from "links nowhere": QV-071 pulled this link because /methodology 404'd
    render(<BacktestResults backtest={backtest} />);
    expect(screen.getByRole("link", { name: /methodology/i })).toHaveAttribute(
      "href",
      "/methodology",
    );
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Decomposition } from "@/components/decomposition";
import type { DecompositionResponse } from "@/lib/api/queries";

const data: DecompositionResponse = {
  symbol: "TCS",
  as_of: "2026-07-07",
  composite: 40,
  sum_of_contributions: 40,
  factors: [
    {
      factor_key: "ret_6m",
      category: "momentum",
      raw_value: 0.1,
      zscore: 0.3,
      percentile_sector: 60,
      percentile_universe: 65,
      contribution: 25,
      as_of: "2026-07-07",
    },
    {
      factor_key: "beta",
      category: "risk",
      raw_value: 1,
      zscore: 0,
      percentile_sector: 50,
      percentile_universe: 55,
      contribution: 15,
      as_of: "2026-07-07",
    },
  ],
};

describe("Decomposition", () => {
  it("renders factors, PIT dates, and a Σ = composite reconciliation", () => {
    render(<Decomposition data={data} />);
    expect(screen.getByText("ret_6m")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(screen.getByText(/Σ contributions = composite/)).toBeInTheDocument();
    expect(screen.getByText("40.0 / 40.0")).toBeInTheDocument();
  });

  it("flags a mismatch when contributions do not reconcile", () => {
    render(<Decomposition data={{ ...data, sum_of_contributions: 30 }} />);
    expect(screen.getByText(/Σ contributions ≠ composite/)).toBeInTheDocument();
  });
});

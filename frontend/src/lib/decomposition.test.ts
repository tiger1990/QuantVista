import { describe, expect, it } from "vitest";

import type { FactorContribution } from "@/lib/api/queries";
import { groupByCategory, sumsToComposite } from "@/lib/decomposition";

function fc(over: Partial<FactorContribution>): FactorContribution {
  return {
    factor_key: "x",
    category: "momentum",
    raw_value: 0,
    zscore: 0,
    percentile_sector: 0,
    percentile_universe: 0,
    contribution: 0,
    as_of: "2026-07-07",
    ...over,
  };
}

describe("sumsToComposite", () => {
  it("holds within tolerance (US-02 invariant)", () => {
    expect(sumsToComposite(50.0, 50.005)).toBe(true);
    expect(sumsToComposite(50.0, 51)).toBe(false);
  });
});

describe("groupByCategory", () => {
  it("groups, totals, and orders by total desc", () => {
    const groups = groupByCategory([
      fc({ category: "momentum", contribution: 10 }),
      fc({ category: "risk", contribution: 30 }),
      fc({ category: "momentum", contribution: 5 }),
    ]);
    expect(groups.map((g) => g.category)).toEqual(["risk", "momentum"]);
    expect(groups[1].total).toBe(15);
    expect(groups[0].factors).toHaveLength(1);
  });
});

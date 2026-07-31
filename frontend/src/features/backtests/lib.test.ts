import { describe, expect, it } from "vitest";

import {
  equityChartData,
  fmtPct,
  fmtRatio,
  metricGroups,
  presetRange,
  rangeDays,
  signOf,
  tierFrom,
} from "./lib";

describe("tierFrom", () => {
  it("maps entitlements to a tier", () => {
    expect(tierFrom(undefined)).toBe("free");
    expect(tierFrom({ backtest: false })).toBe("free");
    expect(tierFrom({ backtest: true, backtest_full: false })).toBe("pro");
    expect(tierFrom({ backtest: true, backtest_full: true })).toBe("quant");
  });
});

describe("formatting (Decimal-string safe)", () => {
  it("formats fractions as percentages", () => {
    expect(fmtPct("0.1234")).toBe("12.34%");
    expect(fmtPct("-0.5")).toBe("-50.00%");
    expect(fmtPct(undefined)).toBe("0.00%");
  });
  it("formats ratios", () => {
    expect(fmtRatio("1.2345")).toBe("1.23");
    expect(fmtRatio("garbage")).toBe("0.00");
  });
  it("signs values", () => {
    expect(signOf("0.1")).toBe("pos");
    expect(signOf("-0.1")).toBe("neg");
    expect(signOf("0")).toBe("zero");
  });
});

describe("preset ranges", () => {
  it("builds a trailing window and computes its length", () => {
    const { start, end } = presetRange(12, new Date("2024-06-30T00:00:00Z"));
    expect(end).toBe("2024-06-30");
    expect(start).toBe("2023-06-30");
    expect(rangeDays(start, end)).toBeLessThanOrEqual(366);
  });
});

describe("metricGroups", () => {
  it("groups the suite into labelled rows", () => {
    const groups = metricGroups({
      total_return: "0.2",
      cagr: "0.1",
      hit_rate: "0.55",
      ann_vol: "0.15",
      max_drawdown: "-0.1",
      sharpe: "1.2",
      sortino: "1.5",
      benchmark_return: "0.12",
      excess_return: "0.08",
      beta: "0.9",
      tracking_error: "0.05",
      information_ratio: "0.7",
      avg_turnover: "0.3",
      avg_exposure: "0.95",
      n_rebalances: 12,
    });
    expect(groups.map((g) => g.title)).toEqual(["Return", "Risk", "vs Benchmark", "Activity"]);
    const total = groups[0].rows[0];
    expect(total).toMatchObject({ label: "Total return", value: "20.00%", sign: "pos" });
    const rebal = groups[3].rows.find((r) => r.label === "Rebalances");
    expect(rebal?.value).toBe("12");
  });
});

describe("equityChartData", () => {
  it("maps the equity_curve series to numbers", () => {
    const data = equityChartData({
      equity_curve: [
        { as_of: "2024-01-01", strategy: "1.0", benchmark: "1.0" },
        { as_of: "2024-02-01", strategy: "1.1", benchmark: "1.05" },
      ],
    });
    expect(data).toEqual([
      { date: "2024-01-01", strategy: 1, benchmark: 1 },
      { date: "2024-02-01", strategy: 1.1, benchmark: 1.05 },
    ]);
  });
  it("tolerates a missing curve", () => {
    expect(equityChartData({})).toEqual([]);
  });
});

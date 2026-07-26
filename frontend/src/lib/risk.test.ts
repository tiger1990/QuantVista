import { describe, expect, it } from "vitest";

import { drawdownChartData, fmtNum, fmtPct, sectorChartData } from "./risk";

describe("fmtPct", () => {
  it("formats a Decimal-string as a percentage", () => {
    expect(fmtPct("0.1234")).toBe("12.34%");
    expect(fmtPct("0")).toBe("0.00%");
  });
  it("renders an em dash for null/undefined", () => {
    expect(fmtPct(null)).toBe("—");
    expect(fmtPct(undefined)).toBe("—");
  });
});

describe("fmtNum", () => {
  it("formats a Decimal-string to fixed digits", () => {
    expect(fmtNum("1.375")).toBe("1.38");
    expect(fmtNum("1.2", 1)).toBe("1.2");
  });
  it("renders an em dash for null", () => {
    expect(fmtNum(null)).toBe("—");
  });
});

describe("sectorChartData", () => {
  it("maps sector→weight to %-points sorted descending", () => {
    const data = sectorChartData({ IT: "0.25", Energy: "0.75" });
    expect(data).toEqual([
      { sector: "Energy", pct: 75 },
      { sector: "IT", pct: 25 },
    ]);
  });
  it("handles an empty map", () => {
    expect(sectorChartData({})).toEqual([]);
  });
});

describe("drawdownChartData", () => {
  it("maps the dated series to %-points (≤ 0), preserving order", () => {
    const data = drawdownChartData([
      { date: "2026-01-01", value: "0" },
      { date: "2026-01-02", value: "-0.05" },
    ]);
    expect(data).toEqual([
      { date: "2026-01-01", pct: 0 },
      { date: "2026-01-02", pct: -5 },
    ]);
  });
  it("handles an empty series", () => {
    expect(drawdownChartData([])).toEqual([]);
  });
});

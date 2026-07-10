import { describe, expect, it } from "vitest";

import {
  COMPARE_MAX,
  DEFAULT_SORT,
  decodeCriteria,
  decodeFilters,
  encodeCriteria,
  encodeFilters,
  validateClause,
  validateSort,
} from "./screener";

describe("validateClause", () => {
  it("normalizes a numeric clause and coerces the value to a number", () => {
    expect(validateClause("composite_score", "gte", "70")).toEqual({
      field: "composite_score",
      op: "gte",
      value: 70,
    });
  });

  it("rejects a non-numeric value on a numeric field", () => {
    expect(validateClause("pe", "lte", "cheap")).toBeNull();
  });

  it("rejects an operator outside the numeric allow-list", () => {
    expect(validateClause("roe", "contains", "5")).toBeNull();
  });

  it("accepts eq on a categorical field and trims the value", () => {
    expect(validateClause("sector", "eq", "  Financials ")).toEqual({
      field: "sector",
      op: "eq",
      value: "Financials",
    });
  });

  it("rejects a non-eq operator on a categorical field", () => {
    expect(validateClause("sector", "gte", "Financials")).toBeNull();
  });

  it("rejects an empty categorical value", () => {
    expect(validateClause("market_cap_bucket", "eq", "   ")).toBeNull();
  });

  it("rejects a field outside the allow-list (injection guard)", () => {
    expect(validateClause("id", "eq", "x")).toBeNull();
  });
});

describe("validateSort", () => {
  it("defaults to composite desc when absent", () => {
    expect(validateSort(null)).toBe(DEFAULT_SORT);
  });

  it("passes an allow-listed descending sort", () => {
    expect(validateSort("-pe")).toBe("-pe");
  });

  it("passes symbol (ascending, non-score sort field)", () => {
    expect(validateSort("symbol")).toBe("symbol");
  });

  it("falls back to default for an unknown sort field", () => {
    expect(validateSort("-hacker")).toBe(DEFAULT_SORT);
  });
});

describe("filter URL codec", () => {
  it("round-trips a mixed filter set", () => {
    const filters = [
      { field: "composite_score", op: "gte", value: 70 },
      { field: "sector", op: "eq", value: "Financials" },
    ];
    expect(decodeFilters(encodeFilters(filters))).toEqual(filters);
  });

  it("drops malformed clauses instead of throwing (hand-edited URL is safe)", () => {
    expect(decodeFilters("composite_score:gte:70;garbage;id:eq:1")).toEqual([
      { field: "composite_score", op: "gte", value: 70 },
    ]);
  });

  it("decodes an empty string to no filters", () => {
    expect(decodeFilters("")).toEqual([]);
    expect(decodeFilters(null)).toEqual([]);
  });
});

describe("criteria URL codec", () => {
  it("omits default market and default sort from the encoded params", () => {
    const encoded = encodeCriteria({ market: "NSE", filters: [], sort: DEFAULT_SORT });
    expect(encoded).toEqual({});
  });

  it("encodes non-default market, filters, and sort", () => {
    const encoded = encodeCriteria({
      market: "BSE",
      filters: [{ field: "pe", op: "lte", value: 25 }],
      sort: "-roe",
    });
    expect(encoded).toEqual({ market: "BSE", f: "pe:lte:25", sort: "-roe" });
  });

  it("restores criteria from URL params (deep-link)", () => {
    const params = new URLSearchParams({ f: "composite_score:gte:70", sort: "-pe" });
    expect(decodeCriteria(params)).toEqual({
      market: "NSE",
      filters: [{ field: "composite_score", op: "gte", value: 70 }],
      sort: "-pe",
    });
  });
});

describe("COMPARE_MAX", () => {
  it("caps comparison at four stocks", () => {
    expect(COMPARE_MAX).toBe(4);
  });
});

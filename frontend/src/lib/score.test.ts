import { describe, expect, it } from "vitest";

import { formatScore, scoreTone, toneTextClass } from "@/lib/score";

describe("scoreTone", () => {
  it("buckets a composite by threshold", () => {
    expect(scoreTone(75)).toBe("positive");
    expect(scoreTone(60)).toBe("positive"); // boundary inclusive
    expect(scoreTone(50)).toBe("neutral");
    expect(scoreTone(40)).toBe("neutral"); // boundary
    expect(scoreTone(39.9)).toBe("negative");
  });

  it("treats null/undefined as neutral", () => {
    expect(scoreTone(null)).toBe("neutral");
    expect(scoreTone(undefined)).toBe("neutral");
  });
});

describe("formatScore", () => {
  it("renders one decimal, rounding", () => {
    expect(formatScore(84.25)).toBe("84.3");
    expect(formatScore(50)).toBe("50.0");
  });

  it("renders an em dash when unscored", () => {
    expect(formatScore(null)).toBe("—");
    expect(formatScore(undefined)).toBe("—");
  });
});

describe("toneTextClass", () => {
  it("maps tone to a semantic token class", () => {
    expect(toneTextClass("positive")).toContain("positive");
    expect(toneTextClass("negative")).toContain("negative");
    expect(toneTextClass("neutral")).toContain("muted");
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DISCLAIMER } from "@/lib/disclaimer";
import { CATEGORY_WEIGHTS, MODEL_VERSION, SLIPPAGE_BPS } from "@/lib/methodology";

import MethodologyPage from "./page";

describe("Methodology page", () => {
  it("renders without any authenticated session", () => {
    // it lives outside the (app) group on purpose: that layout redirects anon users to /login,
    // and a trust page behind auth is invisible to the people it exists to convince
    render(<MethodologyPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /methodology & disclaimer/i }),
    ).toBeVisible();
  });

  it("documents every required section", () => {
    render(<MethodologyPage />);
    for (const heading of [
      /what this is/i,
      /how scores are computed/i,
      /point-in-time and survivorship/i,
      /what a backtest assumes/i,
      /reproducibility/i,
    ]) {
      expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
    }
  });

  it("publishes the composite weights and the methodology version", () => {
    render(<MethodologyPage />);
    for (const { category, weight } of CATEGORY_WEIGHTS) {
      expect(screen.getByText(category)).toBeInTheDocument();
      expect(screen.getAllByText(`${(weight * 100).toFixed(0)}%`).length).toBeGreaterThan(0);
    }
    expect(screen.getByText(MODEL_VERSION)).toBeInTheDocument();
  });

  it("states the modelled cost assumptions", () => {
    render(<MethodologyPage />);
    expect(screen.getByText(new RegExp(`${SLIPPAGE_BPS} bps slippage`, "i"))).toBeInTheDocument();
  });

  it("says plainly that the benchmark is a proxy, not the licensed index", () => {
    // the caveat most likely to be quietly dropped, and the one that would mislead a reader.
    // asserted on rendered text because the sentence spans inline <strong> elements
    const { container } = render(<MethodologyPage />);
    expect(screen.getByText(/benchmark is a proxy, not the published index/i)).toBeInTheDocument();
    expect(container.textContent).toMatch(/not.{0,20}the licensed Nifty 200 Total Return Index/i);
    expect(container.textContent).toMatch(/equal-weight buy-and-hold of the universe/i);
  });

  it("warns that out-of-coverage ranges return zeroed results rather than errors", () => {
    render(<MethodologyPage />);
    expect(screen.getByText(/results depend on ingested data coverage/i)).toBeInTheDocument();
    expect(screen.getByText(/degenerate, all-zero/i)).toBeInTheDocument();
  });

  it("is honest that the reproducibility hash covers the recipe, not the data", () => {
    render(<MethodologyPage />);
    expect(
      screen.getByText(/the fingerprint covers the recipe, not the data/i),
    ).toBeInTheDocument();
  });

  it("carries the non-advice posture, sourced from the shared constant", () => {
    render(<MethodologyPage />);
    expect(
      screen.getAllByText(new RegExp(DISCLAIMER.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"))
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/nothing here is personalised/i)).toBeInTheDocument();
    expect(screen.getByText(/no execution, custody or brokerage/i)).toBeInTheDocument();
  });
});

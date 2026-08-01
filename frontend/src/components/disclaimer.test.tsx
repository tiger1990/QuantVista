import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DISCLAIMER } from "@/lib/disclaimer";

import { Disclaimer } from "./disclaimer";

describe("Disclaimer", () => {
  it("renders the shared non-advice constant, not a per-surface copy", () => {
    render(<Disclaimer />);
    expect(screen.getByText(new RegExp(DISCLAIMER.replace(/\./g, "\\."), "i"))).toBeInTheDocument();
  });

  it("links to the methodology page", () => {
    // this component renders on every score surface, so one link here covers them all (QV-070 AC-7)
    render(<Disclaimer />);
    expect(screen.getByRole("link", { name: /methodology/i })).toHaveAttribute(
      "href",
      "/methodology",
    );
  });
});

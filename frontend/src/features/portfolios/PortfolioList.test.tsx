import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Portfolio } from "@/lib/api/queries";

import { PortfolioList } from "./PortfolioList";

const del = { mutate: vi.fn(), isPending: false };
const create = { mutate: vi.fn(), isPending: false, isError: false, isSuccess: false, error: null };

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useDeletePortfolio: () => del, useCreatePortfolio: () => create };
});

const PORTFOLIO: Portfolio = {
  id: "pf-1",
  name: "Growth",
  benchmark: "NIFTY200_TRI",
  base_currency: "INR",
  created_at: "2026-07-20T00:00:00Z",
  updated_at: "2026-07-20T00:00:00Z",
};

describe("PortfolioList", () => {
  it("shows the empty state when there are no portfolios", () => {
    render(<PortfolioList portfolios={[]} atLimit={false} />);
    expect(screen.getByText(/no portfolios yet/i)).toBeInTheDocument();
  });

  it("renders a portfolio and deletes on click", () => {
    render(<PortfolioList portfolios={[PORTFOLIO]} atLimit={false} />);
    expect(screen.getByText("Growth")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /delete portfolio Growth/i }));
    expect(del.mutate).toHaveBeenCalledWith("pf-1");
  });

  it("shows the upgrade CTA when at the portfolio limit", () => {
    render(<PortfolioList portfolios={[PORTFOLIO]} atLimit={true} />);
    expect(screen.getByText(/reached your portfolio limit/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see plans/i })).toBeInTheDocument();
  });
});

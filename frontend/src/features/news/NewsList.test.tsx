import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NewsItem } from "@/lib/api/queries";

import { NewsList } from "./NewsList";

const ITEM: NewsItem = {
  id: "1",
  headline: "Nifty hits record high",
  summary: "Benchmarks rallied on strong earnings.",
  source: "Moneycontrol",
  source_url: "https://example.com/nifty",
  published_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
};

describe("NewsList", () => {
  it("renders a headline linking out safely (rel=noopener, new tab)", () => {
    render(<NewsList items={[ITEM]} />);
    const link = screen.getByRole("link", { name: /Nifty hits record high/i });
    expect(link).toHaveAttribute("href", "https://example.com/nifty");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/Moneycontrol · 3h ago/)).toBeInTheDocument();
  });

  it("shows the empty message when there are no items", () => {
    render(<NewsList items={[]} emptyMessage="No recent news for RELIANCE." />);
    expect(screen.getByText("No recent news for RELIANCE.")).toBeInTheDocument();
  });

  it("shows a loading state", () => {
    render(<NewsList items={[]} isLoading />);
    expect(screen.getByText(/loading news/i)).toBeInTheDocument();
  });
});

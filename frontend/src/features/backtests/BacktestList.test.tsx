import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BacktestListItem } from "@/lib/api/queries";

import { BacktestList } from "./BacktestList";

const items: BacktestListItem[] = [
  {
    id: "run-1",
    status: "succeeded",
    type: "factor_strategy",
    universe: "NIFTY200",
    start: "2025-07-01",
    end: "2026-07-01",
    created_at: "2026-07-30T10:00:00+05:30",
  },
  {
    id: "run-2",
    status: "failed",
    type: "factor_strategy",
    universe: "NIFTY200",
    start: "2024-01-01",
    end: "2024-12-31",
    created_at: "2026-07-29T10:00:00+05:30",
  },
];

describe("BacktestList", () => {
  it("renders an empty state with no runs", () => {
    render(<BacktestList items={[]} onSelect={vi.fn()} />);
    expect(screen.getByText(/no backtests yet/i)).toBeInTheDocument();
  });

  it("opens a past run when its row is clicked", () => {
    // regression: rows were plain divs, so a succeeded run could not be reviewed without re-running
    const onSelect = vi.fn();
    render(<BacktestList items={items} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /succeeded/i }));
    expect(onSelect).toHaveBeenCalledWith("run-1");
  });

  it("every run is an actionable row, whatever its status", () => {
    render(<BacktestList items={items} onSelect={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(items.length);
  });

  it("marks the open run as current", () => {
    render(<BacktestList items={items} selectedId="run-2" onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: /failed/i })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /succeeded/i })).not.toHaveAttribute("aria-current");
  });
});

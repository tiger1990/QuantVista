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

describe("BacktestList delete", () => {
  it("shows no delete control when the page passes no handler", () => {
    render(<BacktestList items={items} onSelect={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /^delete backtest/i })).not.toBeInTheDocument();
  });

  it("shows a delete control on every row without needing hover", () => {
    // the control is always visible by request — no opacity-0/group-hover reveal
    render(<BacktestList items={items} onSelect={vi.fn()} onDelete={vi.fn()} />);
    const buttons = screen.getAllByRole("button", { name: /^delete backtest/i });
    expect(buttons).toHaveLength(items.length);
    for (const b of buttons) {
      expect(b.className).not.toMatch(/opacity-0|group-hover/);
    }
  });

  it("asks before deleting — one click does not destroy the run", () => {
    const onDelete = vi.fn();
    render(<BacktestList items={items} onSelect={vi.fn()} onDelete={onDelete} />);
    fireEvent.click(screen.getAllByRole("button", { name: /^delete backtest/i })[0]);
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByText("Delete?")).toBeInTheDocument();
  });

  it("deletes the right run once confirmed", () => {
    const onDelete = vi.fn();
    render(<BacktestList items={items} onSelect={vi.fn()} onDelete={onDelete} />);
    fireEvent.click(screen.getAllByRole("button", { name: /^delete backtest/i })[1]);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledWith("run-2");
  });

  it("cancel abandons the delete", () => {
    const onDelete = vi.fn();
    render(<BacktestList items={items} onSelect={vi.fn()} onDelete={onDelete} />);
    fireEvent.click(screen.getAllByRole("button", { name: /^delete backtest/i })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByText("Delete?")).not.toBeInTheDocument();
  });

  it("does not open a run while it is being deleted", () => {
    const onSelect = vi.fn();
    render(
      <BacktestList items={items} onSelect={onSelect} onDelete={vi.fn()} deletingId="run-1" />,
    );
    fireEvent.click(screen.getByRole("button", { name: /succeeded/i }));
    expect(onSelect).not.toHaveBeenCalled();
  });
});

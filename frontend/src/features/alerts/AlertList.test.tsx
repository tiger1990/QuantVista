import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AlertRule } from "@/lib/api/queries";

import { AlertList } from "./AlertList";

const del = { mutate: vi.fn(), isPending: false };

// the mock is module-level; without a reset, one test sees the previous test's calls
beforeEach(() => del.mutate.mockReset());

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useDeleteAlert: () => del };
});

const RULE: AlertRule = {
  id: "rule-1",
  scope: "stock",
  target_id: "stock-uuid",
  target_symbol: "DIXON",
  condition: { metric: "composite_score", op: "lt", value: 50 },
  channel: "email",
  is_active: true,
  created_at: "2026-07-12T00:00:00Z",
};

describe("AlertList", () => {
  it("shows the empty state when there are no rules", () => {
    render(<AlertList rules={[]} />);
    expect(screen.getByText(/no alerts yet/i)).toBeInTheDocument();
  });

  it("renders a rule's symbol, condition and channel, and deletes on click", () => {
    render(<AlertList rules={[RULE]} />);
    expect(screen.getByText("DIXON")).toBeInTheDocument();
    expect(screen.getByText(/composite score < 50/i)).toBeInTheDocument();
    expect(screen.getByText(/email/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /delete alert on DIXON/i }));
    expect(del.mutate).not.toHaveBeenCalled(); // deleting a rule silently stops future alerts

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(del.mutate).toHaveBeenCalledWith("rule-1");
  });

  it("cancelling leaves the rule in place", () => {
    render(<AlertList rules={[RULE]} />);
    fireEvent.click(screen.getByRole("button", { name: /delete alert on DIXON/i }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(del.mutate).not.toHaveBeenCalled();
  });
});

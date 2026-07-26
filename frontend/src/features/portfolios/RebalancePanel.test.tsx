import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RebalanceError, type RebalanceResponse } from "@/lib/api/queries";

import { RebalancePanel } from "./RebalancePanel";

type RebalanceState = {
  mutate: ReturnType<typeof vi.fn>;
  data: RebalanceResponse | undefined;
  error: unknown;
  isPending: boolean;
};
type ApplyState = { mutate: ReturnType<typeof vi.fn>; isPending: boolean };

let rebalance: RebalanceState;
let apply: ApplyState;

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useRebalance: () => rebalance, useApplyTargets: () => apply };
});

const PLAN: RebalanceResponse = {
  as_of_date: "2026-07-20",
  total_drift: "0.2500",
  needs_rebalance: true,
  trades: [
    {
      stock_id: "s1",
      symbol: "AAA",
      direction: "buy",
      current_weight: "0.25",
      target_weight: "0.50",
      delta_weight: "0.25",
    },
    {
      stock_id: "s2",
      symbol: "BBB",
      direction: "sell",
      current_weight: "0.75",
      target_weight: "0.50",
      delta_weight: "-0.25",
    },
  ],
};

beforeEach(() => {
  rebalance = { mutate: vi.fn(), data: undefined, error: null, isPending: false };
  apply = { mutate: vi.fn(), isPending: false };
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

const clickCheck = () =>
  fireEvent.click(screen.getByRole("button", { name: /check drift/i }));

describe("RebalancePanel", () => {
  it("prompts to set targets on a no_targets (422) result", () => {
    rebalance.mutate.mockImplementation((_t: string, opts?: { onError?: (e: unknown) => void }) =>
      opts?.onError?.(new RebalanceError("no_targets")),
    );
    render(<RebalancePanel portfolioId="p" hasHoldings />);
    clickCheck();
    expect(screen.getByText(/no target weights set/i)).toBeInTheDocument();
    expect(screen.getByText(/run an optimization and set targets/i)).toBeInTheDocument();
  });

  it("renders trades with buy/sell tone and drift", () => {
    rebalance.mutate.mockImplementation(
      (_t: string, opts?: { onSuccess?: (d: RebalanceResponse) => void }) => opts?.onSuccess?.(PLAN),
    );
    render(<RebalancePanel portfolioId="p" hasHoldings />);
    clickCheck();
    expect(screen.getAllByText("25.00%").length).toBeGreaterThan(0); // drift + weights
    expect(screen.getByText(/rebalance suggested/i)).toBeInTheDocument();
    expect(screen.getByText("buy")).toBeInTheDocument();
    expect(screen.getByText("sell")).toBeInTheDocument();
  });

  it("applies one PUT per trade with the suggested target_weight", () => {
    rebalance.mutate.mockImplementation(
      (_t: string, opts?: { onSuccess?: (d: RebalanceResponse) => void }) => opts?.onSuccess?.(PLAN),
    );
    render(<RebalancePanel portfolioId="p" hasHoldings />);
    clickCheck();
    fireEvent.click(screen.getByRole("button", { name: /apply targets/i }));
    expect(apply.mutate).toHaveBeenCalledWith([
      { stock_id: "s1", target_weight: "0.50" },
      { stock_id: "s2", target_weight: "0.50" },
    ]);
  });

  it("checks drift with the entered threshold", () => {
    render(<RebalancePanel portfolioId="p" hasHoldings />);
    fireEvent.change(screen.getByLabelText(/drift threshold/i), { target: { value: "0.1" } });
    clickCheck();
    expect(rebalance.mutate).toHaveBeenCalledWith("0.1", expect.anything());
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OptimizeError, type OptimizeResponse } from "@/lib/api/queries";

import { OptimizePanel } from "./OptimizePanel";

type OptimizeState = {
  mutate: ReturnType<typeof vi.fn>;
  reset: ReturnType<typeof vi.fn>;
  isPending: boolean;
  data: OptimizeResponse | null;
  error: unknown;
};

let state: OptimizeState;

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useOptimize: () => state };
});

beforeEach(() => {
  state = { mutate: vi.fn(), reset: vi.fn(), isPending: false, data: null, error: null };
});

const RESULT: OptimizeResponse = {
  weights: { a: "0.6", b: "0.4" },
  expected_return: "0.1234",
  expected_volatility: "0.1800",
  constraints: [{ kind: "full_investment", satisfied: true, detail: "weights sum to 1.0" }],
};

const noop = () => {};

describe("OptimizePanel", () => {
  it("gates optimization behind an upgrade CTA on Free", () => {
    render(<OptimizePanel portfolioId="p" canOptimize={false} hasHoldings onOptimized={noop} />);
    expect(screen.getByText(/paid feature/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see plans/i })).toBeInTheDocument();
  });

  it("renders metrics and per-constraint status on success", () => {
    state.data = RESULT;
    render(<OptimizePanel portfolioId="p" canOptimize hasHoldings onOptimized={noop} />);
    expect(screen.getByText("12.34%")).toBeInTheDocument(); // expected return
    expect(screen.getByText("18.00%")).toBeInTheDocument(); // expected volatility
    expect(screen.getByText(/weights sum to 1.0/i)).toBeInTheDocument();
  });

  it("shows the binding constraint on an infeasible result (US-03)", () => {
    state.error = new OptimizeError("infeasible", "sector 'IT' weight 0.90 vs cap 0.30");
    render(<OptimizePanel portfolioId="p" canOptimize hasHoldings onOptimized={noop} />);
    expect(screen.getByText(/no feasible allocation/i)).toBeInTheDocument();
    expect(screen.getByText(/sector 'IT' weight 0.90 vs cap 0.30/i)).toBeInTheDocument();
  });

  it("offers both optimization methods and switching to risk parity disables the objective", () => {
    render(<OptimizePanel portfolioId="p" canOptimize hasHoldings onOptimized={noop} />);
    const method = screen.getByLabelText<HTMLSelectElement>("Method");
    expect([...method.options].map((o) => o.value)).toEqual(["mean_variance", "risk_parity"]);
    fireEvent.change(method, { target: { value: "risk_parity" } });
    expect(screen.getByLabelText<HTMLSelectElement>("Objective")).toBeDisabled();
    expect(screen.getByText(/no return target/i)).toBeInTheDocument();
  });

  it("runs the selected method (risk parity) without a return target", () => {
    render(<OptimizePanel portfolioId="p" canOptimize hasHoldings onOptimized={noop} />);
    fireEvent.change(screen.getByLabelText("Method"), { target: { value: "risk_parity" } });
    fireEvent.click(screen.getByRole("button", { name: /run optimization/i }));
    expect(state.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ method: "risk_parity" }),
      expect.anything(),
    );
    expect(state.mutate.mock.calls[0][0].constraints).not.toHaveProperty("target_return");
  });
});

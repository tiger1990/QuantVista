import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SubmitBacktestError } from "@/lib/api/queries";

import { BacktestSetupForm, submitErrorMessage } from "./BacktestSetupForm";

const submit = { mutate: vi.fn(), isPending: false };

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useSubmitBacktest: () => submit };
});

beforeEach(() => {
  submit.mutate.mockReset();
  submit.isPending = false;
});

describe("BacktestSetupForm tier gating", () => {
  it("free tier shows an upsell, not the form", () => {
    render(<BacktestSetupForm tier="free" onQueued={vi.fn()} />);
    expect(screen.getByText(/paid feature/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run backtest/i })).not.toBeInTheDocument();
  });

  it("pro tier offers ≤1y presets and no custom dates", () => {
    render(<BacktestSetupForm tier="pro" onQueued={vi.fn()} />);
    expect(screen.getByRole("button", { name: "1Y" })).toBeInTheDocument();
    expect(screen.getByText(/custom ranges need quant/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/start/i)).not.toBeInTheDocument();
  });

  it("quant tier exposes custom start/end dates", () => {
    render(<BacktestSetupForm tier="quant" onQueued={vi.fn()} />);
    expect(screen.getByText("Start")).toBeInTheDocument();
    expect(screen.getByText("End")).toBeInTheDocument();
  });
});

describe("BacktestSetupForm submit", () => {
  it("submits a spec on run (pro preset)", () => {
    render(<BacktestSetupForm tier="pro" onQueued={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    expect(submit.mutate).toHaveBeenCalledTimes(1);
    const spec = submit.mutate.mock.calls[0][0];
    expect(spec).toMatchObject({
      type: "factor_strategy",
      universe: "NIFTY200",
      rules: { rank_by: "composite", top_n: 20, rebalance: "monthly" },
    });
  });

  it("blocks an inverted custom range (quant) before submitting", () => {
    const { container } = render(<BacktestSetupForm tier="quant" onQueued={vi.fn()} />);
    const [startInput] = Array.from(container.querySelectorAll('input[type="date"]'));
    // the default range is valid (start < end); push start past end to invert it
    fireEvent.change(startInput, { target: { value: "2099-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: /run backtest/i }));
    expect(submit.mutate).not.toHaveBeenCalled();
    expect(screen.getByText(/start date must be before/i)).toBeInTheDocument();
  });

  it("defaults the custom range to a trailing year, not a hardcoded past one", () => {
    // regression: fixed 2020 defaults fall outside the ingested price history → empty tearsheet
    const { container } = render(<BacktestSetupForm tier="quant" onQueued={vi.fn()} />);
    const [startInput, endInput] = Array.from(
      container.querySelectorAll<HTMLInputElement>('input[type="date"]'),
    );
    const thisYear = new Date().getFullYear();
    expect(Number(endInput.value.slice(0, 4))).toBe(thisYear);
    expect(Number(startInput.value.slice(0, 4))).toBe(thisYear - 1);
    expect(Date.parse(startInput.value)).toBeLessThan(Date.parse(endInput.value));
  });
});

describe("submitErrorMessage", () => {
  it("blames the plan on 403", () => {
    expect(submitErrorMessage(new SubmitBacktestError("entitlement"))).toMatch(/quant plan/i);
  });

  it("blames the inputs only on a real 422", () => {
    expect(submitErrorMessage(new SubmitBacktestError("invalid"))).toMatch(/check the inputs/i);
  });

  it("does NOT blame the inputs when the API is unreachable (404/5xx/network)", () => {
    // regression: a stale API served 404 and the UI said "check the inputs" on a valid spec
    for (const e of [new SubmitBacktestError("unknown"), new TypeError("fetch failed")]) {
      const msg = submitErrorMessage(e);
      expect(msg).not.toMatch(/check the inputs/i);
      expect(msg).toMatch(/couldn't reach/i);
    }
  });
});

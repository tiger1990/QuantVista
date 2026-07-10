import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterBuilder } from "./FilterBuilder";

describe("FilterBuilder", () => {
  it("runs with a validated numeric clause", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn();
    render(<FilterBuilder initialFilters={[]} onRun={onRun} />);

    await user.type(screen.getByLabelText("Value"), "70");
    await user.click(screen.getByRole("button", { name: /run screen/i }));

    expect(onRun).toHaveBeenCalledWith([{ field: "composite_score", op: "gte", value: 70 }]);
  });

  it("drops a clause with a non-numeric value on a numeric field", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn();
    render(<FilterBuilder initialFilters={[]} onRun={onRun} />);

    await user.type(screen.getByLabelText("Value"), "cheap");
    await user.click(screen.getByRole("button", { name: /run screen/i }));

    expect(onRun).toHaveBeenCalledWith([]);
  });

  it("forces eq and offers only 'is' when a categorical field is chosen", async () => {
    const user = userEvent.setup();
    const onRun = vi.fn();
    render(<FilterBuilder initialFilters={[]} onRun={onRun} />);

    await user.selectOptions(screen.getByLabelText("Field"), "sector");
    expect(screen.getByLabelText("Operator")).toBeDisabled();

    await user.type(screen.getByLabelText("Value"), "Financials");
    await user.click(screen.getByRole("button", { name: /run screen/i }));

    expect(onRun).toHaveBeenCalledWith([{ field: "sector", op: "eq", value: "Financials" }]);
  });

  it("adds and removes filter rows", async () => {
    const user = userEvent.setup();
    render(<FilterBuilder initialFilters={[]} onRun={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /add filter/i }));
    expect(screen.getAllByLabelText("Value")).toHaveLength(2);

    await user.click(screen.getAllByRole("button", { name: /remove filter/i })[1]);
    expect(screen.getAllByLabelText("Value")).toHaveLength(1);
  });
});

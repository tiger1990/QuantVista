import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeleteButton } from "./delete-button";

const onConfirm = vi.fn();

beforeEach(() => onConfirm.mockReset());

describe("DeleteButton", () => {
  it("does not delete on the first click", () => {
    // the whole point: five surfaces previously destroyed records on a single click
    render(<DeleteButton label="Delete thing" onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete thing" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText("Delete?")).toBeInTheDocument();
  });

  it("deletes once confirmed", () => {
    render(<DeleteButton label="Delete thing" onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete thing" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("cancel abandons the delete and restores the trigger", () => {
    render(<DeleteButton label="Delete thing" onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete thing" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete thing" })).toBeInTheDocument();
  });

  it("is disabled while a delete is in flight", () => {
    render(<DeleteButton label="Delete thing" onConfirm={onConfirm} pending />);
    const trigger = screen.getByRole("button", { name: "Delete thing" });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByText("Delete?")).not.toBeInTheDocument();
  });

  it("carries an accessible name so rows are distinguishable", () => {
    render(<DeleteButton label="Delete portfolio Growth" onConfirm={onConfirm} />);
    expect(screen.getByRole("button", { name: "Delete portfolio Growth" })).toBeInTheDocument();
  });
});

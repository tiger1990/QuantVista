import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SetTargetsButton } from "./SetTargetsButton";

let apply: { mutate: ReturnType<typeof vi.fn>; isPending: boolean };

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useApplyTargets: () => apply };
});

beforeEach(() => {
  apply = { mutate: vi.fn(), isPending: false };
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("SetTargetsButton", () => {
  it("maps optimizer weights to one target per name", () => {
    render(<SetTargetsButton portfolioId="p" weights={{ s1: "0.6", s2: "0.4" }} />);
    fireEvent.click(screen.getByRole("button", { name: /set as targets/i }));
    expect(apply.mutate).toHaveBeenCalledWith([
      { stock_id: "s1", target_weight: "0.6" },
      { stock_id: "s2", target_weight: "0.4" },
    ]);
  });

  it("is disabled with no weights", () => {
    render(<SetTargetsButton portfolioId="p" weights={{}} />);
    expect(screen.getByRole("button", { name: /set as targets/i })).toBeDisabled();
  });
});

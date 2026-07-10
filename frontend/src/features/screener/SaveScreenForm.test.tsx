import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SaveScreenError } from "@/lib/api/queries";

import { SaveScreenForm } from "./SaveScreenForm";

const mutation = {
  mutate: vi.fn(),
  isPending: false,
  isSuccess: false,
  error: null as unknown,
};

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useSaveScreen: () => mutation };
});

const CRITERIA = { market: "NSE", filters: [], sort: "-composite_score" };

describe("SaveScreenForm", () => {
  it("surfaces an upgrade CTA when the save hits the tier limit (403)", () => {
    mutation.error = new SaveScreenError("limit");
    render(<SaveScreenForm criteria={CRITERIA} />);

    expect(screen.getByText(/saved-screen limit/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see plans/i })).toHaveAttribute("href", "/pricing");
  });

  it("shows a name-taken message on 409 conflict", () => {
    mutation.error = new SaveScreenError("conflict");
    render(<SaveScreenForm criteria={CRITERIA} />);

    expect(screen.getByText(/already exists/i)).toBeInTheDocument();
  });

  it("shows an invalid-criteria message on 422", () => {
    mutation.error = new SaveScreenError("invalid");
    render(<SaveScreenForm criteria={CRITERIA} />);

    expect(screen.getByText(/can’t be saved/i)).toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const login = vi.fn();
vi.mock("@/components/auth-provider", () => ({ useAuth: () => ({ login }) }));

import LoginPage from "./page";

describe("LoginPage", () => {
  it("shows Zod validation errors and does not call login on an empty submit", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/enter a valid email/i)).toBeInTheDocument();
    expect(screen.getByText(/enter your password/i)).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });
});

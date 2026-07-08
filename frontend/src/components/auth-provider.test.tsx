import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the generated API client before importing the provider under test.
const post = vi.fn();
const get = vi.fn();
const setToken = vi.fn();
vi.mock("@/lib/api/client", () => ({
  api: { POST: (...a: unknown[]) => post(...a), GET: (...a: unknown[]) => get(...a) },
  setAccessToken: (...a: unknown[]) => setToken(...a),
}));

import { AuthProvider, accessTokenFrom, useAuth } from "@/components/auth-provider";

function Probe() {
  const { status, user } = useAuth();
  return (
    <div>
      status:{status} user:{user?.email ?? "none"}
    </div>
  );
}

describe("accessTokenFrom", () => {
  it("extracts the token from a typed envelope", () => {
    expect(
      accessTokenFrom({
        success: true,
        data: { access_token: "abc", token_type: "bearer" },
        error: null,
        meta: null,
      }),
    ).toBe("abc");
  });

  it("returns null when the token is absent", () => {
    expect(accessTokenFrom(undefined)).toBeNull();
    expect(accessTokenFrom({ success: false, data: null, error: null, meta: null })).toBeNull();
  });
});

describe("AuthProvider", () => {
  beforeEach(() => {
    post.mockReset();
    get.mockReset();
    setToken.mockReset();
  });

  it("resolves to anon when the silent refresh fails", async () => {
    post.mockResolvedValueOnce({ data: undefined, error: { code: "unauthenticated" } });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByText(/status:anon/)).toBeInTheDocument());
  });

  it("resolves to authed and loads the user on a successful refresh", async () => {
    post.mockResolvedValueOnce({
      data: { success: true, data: { access_token: "t", token_type: "bearer" }, error: null },
      error: undefined,
    });
    get.mockResolvedValueOnce({
      data: {
        success: true,
        data: {
          user_id: "u1",
          email: "ada@example.com",
          name: "Ada",
          tenant_id: "t1",
          tenant_name: "Acme",
          role: "member",
          entitlements: {},
        },
        error: null,
      },
      error: undefined,
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByText(/status:authed user:ada@example.com/)).toBeInTheDocument(),
    );
    expect(setToken).toHaveBeenCalledWith("t");
  });
});

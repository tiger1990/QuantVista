import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const DELETE = vi.fn();
const GET = vi.fn();

vi.mock("@/lib/api/client", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), DELETE: (...a: unknown[]) => DELETE(...a) },
  setAccessToken: vi.fn(),
}));

// imported after the mock so the hooks bind to it
const { useBacktests, useDeleteBacktest } = await import("@/lib/api/queries");

function Probe() {
  const list = useBacktests();
  const del = useDeleteBacktest();
  return (
    <div>
      <span data-testid="rows">{(list.data ?? []).map((b) => b.id).join(",") || "empty"}</span>
      <button type="button" onClick={() => del.mutate("run-1")}>
        del
      </button>
    </div>
  );
}

function renderProbe() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Probe />
    </QueryClientProvider>,
  );
}

const row = (id: string) => ({
  id,
  status: "succeeded",
  type: "factor_strategy",
  universe: "NIFTY200",
  start: "2025-07-01",
  end: "2026-07-01",
  created_at: "2026-07-30T10:00:00+05:30",
});

beforeEach(() => {
  GET.mockReset();
  DELETE.mockReset();
});

describe("deleting a run refreshes the history list", () => {
  it("drops the deleted row without a manual reload", async () => {
    // regression: the row stayed visible after a successful delete
    GET.mockResolvedValueOnce({ data: { data: [row("run-1"), row("run-2")] }, error: undefined })
      .mockResolvedValue({ data: { data: [row("run-2")] }, error: undefined });
    DELETE.mockResolvedValue({ data: undefined, error: undefined }); // 204 No Content

    renderProbe();
    await waitFor(() => expect(screen.getByTestId("rows")).toHaveTextContent("run-1,run-2"));

    screen.getByRole("button", { name: "del" }).click();

    await waitFor(() => expect(DELETE).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("rows")).toHaveTextContent("run-2"));
    expect(screen.getByTestId("rows")).not.toHaveTextContent("run-1");
  });

  it("keeps the row when the delete fails", async () => {
    GET.mockResolvedValue({ data: { data: [row("run-1")] }, error: undefined });
    DELETE.mockResolvedValue({ data: undefined, error: { detail: "nope" } });

    renderProbe();
    await waitFor(() => expect(screen.getByTestId("rows")).toHaveTextContent("run-1"));

    screen.getByRole("button", { name: "del" }).click();

    await waitFor(() => expect(DELETE).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("rows")).toHaveTextContent("run-1");
  });
});

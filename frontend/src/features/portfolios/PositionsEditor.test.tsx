import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Position } from "@/lib/api/queries";

import { PositionsEditor } from "./PositionsEditor";

const upsert = { mutate: vi.fn() };
const del = { mutate: vi.fn(), isPending: false };

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return {
    ...actual,
    useUpsertPosition: () => upsert,
    useDeletePosition: () => del,
    useStocks: () => ({ data: { pages: [] } }),
  };
});

const POSITION: Position = {
  id: "1",
  portfolio_id: "p",
  stock_id: "s1",
  symbol: "AAA",
  weight: null,
  target_weight: "0.5",
  shares: null,
  avg_cost: null,
};

beforeEach(() => {
  upsert.mutate.mockClear();
});

describe("PositionsEditor", () => {
  it("exposes both a shares and a target-weight field per holding", () => {
    render(<PositionsEditor portfolioId="p" positions={[POSITION]} />);
    expect(screen.getByLabelText(/shares held of AAA/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/target weight of AAA/i)).toBeInTheDocument();
  });

  it("saves ONLY the shares field on blur (backend COALESCE preserves the target)", () => {
    render(<PositionsEditor portfolioId="p" positions={[POSITION]} />);
    const shares = screen.getByLabelText(/shares held of AAA/i);
    fireEvent.change(shares, { target: { value: "10" } });
    fireEvent.blur(shares);
    expect(upsert.mutate).toHaveBeenCalledWith({ stockId: "s1", body: { shares: "10" } });
  });
});

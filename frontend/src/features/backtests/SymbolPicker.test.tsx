import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useStocks = vi.fn();

vi.mock("@/lib/api/queries", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/queries")>("@/lib/api/queries");
  return { ...actual, useStocks: (...a: unknown[]) => useStocks(...a) };
});

const { SymbolPicker } = await import("./SymbolPicker");

const stock = (id: string, symbol: string, name: string) => ({
  id,
  symbol,
  company_name: name,
  sector: "IT",
  market_cap_bucket: "large",
  market: "NSE",
});

beforeEach(() => {
  useStocks.mockReset();
  useStocks.mockReturnValue({
    isLoading: false,
    data: {
      pages: [{ data: [stock("1", "TCS", "Tata Consultancy"), stock("2", "INFY", "Infosys")] }],
    },
  });
});

describe("SymbolPicker", () => {
  it("adds a searched symbol to the basket", async () => {
    const onChange = vi.fn();
    render(<SymbolPicker selected={[]} onChange={onChange} max={50} />);

    fireEvent.change(screen.getByLabelText(/search symbols/i), { target: { value: "tcs" } });
    await waitFor(() => expect(screen.getByText("Tata Consultancy")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Tata Consultancy"));

    expect(onChange).toHaveBeenCalledWith(["TCS"]);
  });

  it("shows current picks as removable chips", () => {
    const onChange = vi.fn();
    render(<SymbolPicker selected={["TCS", "INFY"]} onChange={onChange} max={50} />);
    fireEvent.click(screen.getByRole("button", { name: /remove tcs/i }));
    expect(onChange).toHaveBeenCalledWith(["INFY"]);
  });

  it("will not add the same symbol twice", async () => {
    const onChange = vi.fn();
    render(<SymbolPicker selected={["TCS"]} onChange={onChange} max={50} />);
    fireEvent.change(screen.getByLabelText(/search symbols/i), { target: { value: "tcs" } });
    await waitFor(() => expect(screen.getByText("added")).toBeInTheDocument());
    expect(onChange).not.toHaveBeenCalled();
  });

  it("stops accepting picks once the basket is full", () => {
    render(<SymbolPicker selected={["A", "B"]} onChange={vi.fn()} max={2} />);
    const input = screen.getByLabelText(/search symbols/i);
    expect(input).toBeDisabled();
    expect(screen.getByPlaceholderText(/basket is full \(2\)/i)).toBeInTheDocument();
  });

  it("reports how full the basket is", () => {
    render(<SymbolPicker selected={["A"]} onChange={vi.fn()} max={50} />);
    expect(screen.getByText(/1\/50 selected/i)).toBeInTheDocument();
  });
});

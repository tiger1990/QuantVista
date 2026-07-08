import type { ColumnDef } from "@tanstack/react-table";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataTable } from "@/components/data-table";

interface Row {
  symbol: string;
}
const columns: ColumnDef<Row, unknown>[] = [
  { accessorKey: "symbol", header: "Symbol", cell: ({ row }) => row.original.symbol },
];

describe("DataTable", () => {
  it("renders a row per datum", () => {
    render(<DataTable columns={columns} data={[{ symbol: "TCS" }, { symbol: "INFY" }]} />);
    expect(screen.getByText("TCS")).toBeInTheDocument();
    expect(screen.getByText("INFY")).toBeInTheDocument();
  });

  it("shows the empty message when there are no rows", () => {
    render(<DataTable columns={columns} data={[]} emptyMessage="No rows here." />);
    expect(screen.getByText("No rows here.")).toBeInTheDocument();
  });
});

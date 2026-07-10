"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";

import type { ScreenerRow } from "@/lib/api/queries";
import { formatScore, scoreTone, toneTextClass } from "@/lib/score";

function scoreCell(value: number | null | undefined) {
  return (
    <span className={`font-medium tabular-nums ${toneTextClass(scoreTone(value))}`}>
      {formatScore(value)}
    </span>
  );
}

function numCell(value: number | null | undefined) {
  return <span className="tabular-nums text-muted-foreground">{value == null ? "—" : value.toFixed(2)}</span>;
}

interface SelectionApi {
  isSelected: (symbol: string) => boolean;
  canSelectMore: boolean;
  onToggle: (symbol: string) => void;
}

/** Screener result columns with a leading compare-selection checkbox (cap-aware). */
export function makeScreenerColumns(selection: SelectionApi): ColumnDef<ScreenerRow, unknown>[] {
  return [
    {
      id: "select",
      header: "",
      enableSorting: false,
      cell: ({ row }) => {
        const symbol = row.original.symbol;
        const selected = selection.isSelected(symbol);
        return (
          <input
            type="checkbox"
            aria-label={`Select ${symbol} to compare`}
            checked={selected}
            disabled={!selected && !selection.canSelectMore}
            onChange={() => selection.onToggle(symbol)}
            className="size-4 cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-40"
          />
        );
      },
    },
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <Link
          href={`/stocks/${row.original.symbol}`}
          className="font-medium hover:text-primary hover:underline"
        >
          {row.original.symbol}
        </Link>
      ),
    },
    {
      accessorKey: "sector",
      header: "Sector",
      enableSorting: false,
      cell: ({ row }) => (
        <span className="text-muted-foreground">{row.original.sector ?? "—"}</span>
      ),
    },
    { accessorKey: "composite_score", header: "Composite", cell: ({ row }) => scoreCell(row.original.composite_score) },
    { accessorKey: "fundamental_score", header: "Fund.", cell: ({ row }) => scoreCell(row.original.fundamental_score) },
    { accessorKey: "momentum_score", header: "Mom.", cell: ({ row }) => scoreCell(row.original.momentum_score) },
    { accessorKey: "quality_score", header: "Qual.", cell: ({ row }) => scoreCell(row.original.quality_score) },
    { accessorKey: "pe", header: "P/E", cell: ({ row }) => numCell(row.original.pe) },
    { accessorKey: "roe", header: "ROE", cell: ({ row }) => numCell(row.original.roe) },
  ];
}

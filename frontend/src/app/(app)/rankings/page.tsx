"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { Disclaimer } from "@/components/disclaimer";
import { type RankingItem, useRankings } from "@/lib/api/queries";
import { formatScore, scoreTone, toneTextClass } from "@/lib/score";

const columns: ColumnDef<RankingItem, unknown>[] = [
  {
    accessorKey: "rank",
    header: "#",
    enableSorting: false,
    cell: ({ row }) => <span className="tabular-nums text-muted-foreground">{row.original.rank}</span>,
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
    accessorKey: "composite_score",
    header: "Composite",
    cell: ({ row }) => {
      const s = row.original.composite_score;
      return (
        <span className={`font-medium tabular-nums ${toneTextClass(scoreTone(s))}`}>
          {formatScore(s)}
        </span>
      );
    },
  },
  {
    accessorKey: "coverage",
    header: "Coverage",
    cell: ({ row }) => {
      const c = row.original.coverage;
      return (
        <span className="tabular-nums text-muted-foreground">
          {c == null ? "—" : `${Math.round(c * 100)}%`}
        </span>
      );
    },
  },
];

export default function RankingsPage() {
  const { data, isLoading, isError } = useRankings();
  const rows = data?.data ?? [];
  const meta = data?.meta as { tier_limit?: number | null; as_of?: string | null } | undefined;

  return (
    <div className="space-y-4">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Rankings</h1>
          <p className="text-sm text-muted-foreground">
            NIFTY 200 by composite score{meta?.as_of ? ` · as of ${meta.as_of}` : ""}
          </p>
        </div>
        {meta?.tier_limit != null ? (
          <span className="rounded-sm bg-muted px-2 py-1 text-xs text-muted-foreground">
            Free tier · top {meta.tier_limit}
          </span>
        ) : null}
      </header>

      {isError ? (
        <p className="py-10 text-center text-sm text-destructive">Could not load rankings.</p>
      ) : (
        <DataTable
          columns={columns}
          data={rows}
          emptyMessage={isLoading ? "Loading…" : "No ranked stocks yet — run the scoring pipeline."}
        />
      )}
      <Disclaimer />
    </div>
  );
}

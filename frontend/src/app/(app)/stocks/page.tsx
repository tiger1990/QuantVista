"use client";

import type { ColumnDef, OnChangeFn, SortingState } from "@tanstack/react-table";
import { Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { DataTable } from "@/components/data-table";
import { Disclaimer } from "@/components/disclaimer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { type StockListItem, useStocks } from "@/lib/api/queries";
import { formatPrice, formatScore, scoreTone, toneTextClass } from "@/lib/score";
import { cn } from "@/lib/utils";

const columns: ColumnDef<StockListItem, unknown>[] = [
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
    accessorKey: "company_name",
    header: "Company",
    cell: ({ row }) => <span className="text-muted-foreground">{row.original.company_name}</span>,
  },
  {
    accessorKey: "sector",
    header: "Sector",
    cell: ({ row }) => row.original.sector ?? "—",
  },
  {
    accessorKey: "close",
    header: "Price",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="tabular-nums text-muted-foreground">{formatPrice(row.original.close)}</span>
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
];

function parseSort(sort: string | null): SortingState {
  if (!sort) return [];
  const [id, dir] = sort.split(".");
  return [{ id, desc: dir === "desc" }];
}

function StocksInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const sector = searchParams.get("sector");
  const q = searchParams.get("q") ?? "";
  const sorting = parseSort(searchParams.get("sort"));

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(searchParams.toString());
    if (value == null) next.delete(key);
    else next.set(key, value);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  // Local input for snappy typing; debounced into the `q` URL param (server-side search).
  const [term, setTerm] = useState(q);
  useEffect(() => {
    const id = setTimeout(() => {
      const v = term.trim();
      if (v !== q) setParam("q", v || null);
    }, 250);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term]);

  const onSortingChange: OnChangeFn<SortingState> = (updater) => {
    const next = typeof updater === "function" ? updater(sorting) : updater;
    const s = next[0];
    setParam("sort", s ? `${s.id}.${s.desc ? "desc" : "asc"}` : null);
  };

  // Unfiltered query drives the sector chips (cached); the table uses the filtered query.
  const all = useStocks({});
  const sectors = Array.from(
    new Set((all.data?.pages.flatMap((p) => p.data ?? []) ?? []).map((r) => r.sector)),
  ).filter((s): s is string => !!s);

  const { data, isLoading, isError, hasNextPage, fetchNextPage, isFetchingNextPage } = useStocks({
    sector,
    q,
  });
  const rows = data?.pages.flatMap((p) => p.data ?? []) ?? [];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Stocks</h1>
          <p className="text-sm text-muted-foreground">
            The NIFTY 200 universe — search, filter, sort, explore.
          </p>
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Search symbol or company…"
            aria-label="Search stocks"
            className="pl-8"
          />
        </div>
      </header>

      <div className="flex flex-wrap gap-1.5">
        <SectorChip label="All" active={!sector} onClick={() => setParam("sector", null)} />
        {sectors.map((s) => (
          <SectorChip key={s} label={s} active={sector === s} onClick={() => setParam("sector", s)} />
        ))}
      </div>

      {isError ? (
        <p className="py-10 text-center text-sm text-destructive">Could not load stocks.</p>
      ) : (
        <DataTable
          columns={columns}
          data={rows}
          sorting={sorting}
          onSortingChange={onSortingChange}
          onRowClick={(row) => router.push(`/stocks/${row.symbol}`)}
          emptyMessage={isLoading ? "Loading…" : "No stocks match."}
        />
      )}

      {hasNextPage ? (
        <div className="flex justify-center">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      ) : null}

      <Disclaimer />
    </div>
  );
}

function SectorChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-sm border px-2.5 py-1 text-xs transition-colors",
        active
          ? "border-primary bg-primary/10 text-foreground"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}

export default function StocksPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <StocksInner />
    </Suspense>
  );
}

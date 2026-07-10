"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";

import { Disclaimer } from "@/components/disclaimer";
import { Card, CardContent } from "@/components/ui/card";
import { CompareMatrix } from "@/features/compare/CompareMatrix";
import { type StockDetail, useCompareDetails } from "@/lib/api/queries";
import { COMPARE_MAX } from "@/lib/screener";

function parseSymbols(raw: string | null): string[] {
  if (!raw) return [];
  return Array.from(
    new Set(
      raw
        .split(",")
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean),
    ),
  ).slice(0, COMPARE_MAX);
}

function Empty({ message }: { message: string }) {
  return (
    <Card>
      <CardContent className="space-y-2 py-12 text-center">
        <p className="text-sm text-muted-foreground">{message}</p>
        <Link href="/screener" className="inline-block text-sm text-primary hover:underline">
          Back to screener
        </Link>
      </CardContent>
    </Card>
  );
}

function CompareInner() {
  const searchParams = useSearchParams();
  const symbols = useMemo(() => parseSymbols(searchParams.get("symbols")), [searchParams]);
  const { isLoading, isError, details } = useCompareDetails(symbols);

  // Drop unknown (404 → null) columns; keep the ones that resolved.
  const found = details.filter((d): d is StockDetail => d !== null);

  return (
    <div className="space-y-5">
      <Link
        href="/screener"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Screener
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Compare</h1>
        <p className="text-sm text-muted-foreground">
          Factor scores and fundamentals, side by side.
        </p>
      </header>

      {symbols.length === 0 ? (
        <Empty message="Pick stocks from the screener to compare them." />
      ) : isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : isError && found.length === 0 ? (
        <Empty message="Could not load these stocks." />
      ) : found.length === 0 ? (
        <Empty message="None of those symbols are in the universe." />
      ) : (
        <CompareMatrix details={found} />
      )}

      <Disclaimer />
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <CompareInner />
    </Suspense>
  );
}

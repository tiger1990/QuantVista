"use client";

import type { OnChangeFn, SortingState } from "@tanstack/react-table";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useMemo, useState } from "react";

import { DataTable } from "@/components/data-table";
import { Disclaimer } from "@/components/disclaimer";
import { Button } from "@/components/ui/button";
import { CompareTray } from "@/features/screener/CompareTray";
import { FilterBuilder } from "@/features/screener/FilterBuilder";
import { makeScreenerColumns } from "@/features/screener/columns";
import { SaveScreenForm } from "@/features/screener/SaveScreenForm";
import { SavedScreens } from "@/features/screener/SavedScreens";
import { useScreener } from "@/lib/api/queries";
import {
  COMPARE_MAX,
  DEFAULT_SORT,
  type FilterClause,
  type ScreenCriteria,
  encodeCriteria,
  decodeCriteria,
} from "@/lib/screener";

/** URL sort string (`-field`/`field`) ⇄ TanStack SortingState. */
function sortToState(sort: string): SortingState {
  const desc = sort.startsWith("-");
  return [{ id: desc ? sort.slice(1) : sort, desc }];
}
function stateToSort(state: SortingState): string {
  const s = state[0];
  if (!s) return DEFAULT_SORT;
  return `${s.desc ? "-" : ""}${s.id}`;
}

function ScreenerInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const applied = useMemo<ScreenCriteria>(
    () => decodeCriteria(searchParams),
    [searchParams],
  );

  const commit = useCallback(
    (criteria: ScreenCriteria) => {
      const params = new URLSearchParams(encodeCriteria(criteria));
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname],
  );

  const { data, isLoading, isError, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useScreener(applied);
  const rows = useMemo(() => data?.pages.flatMap((p) => p.data ?? []) ?? [], [data]);
  const count = data?.pages[0]?.meta?.count as number | undefined;

  // Compare selection (client-only, capped).
  const [selected, setSelected] = useState<string[]>([]);
  const toggle = useCallback(
    (symbol: string) =>
      setSelected((prev) =>
        prev.includes(symbol)
          ? prev.filter((s) => s !== symbol)
          : prev.length >= COMPARE_MAX
            ? prev
            : [...prev, symbol],
      ),
    [],
  );

  const columns = useMemo(
    () =>
      makeScreenerColumns({
        isSelected: (s) => selected.includes(s),
        canSelectMore: selected.length < COMPARE_MAX,
        onToggle: toggle,
      }),
    [selected, toggle],
  );

  const sorting = sortToState(applied.sort ?? DEFAULT_SORT);
  const onSortingChange: OnChangeFn<SortingState> = (updater) => {
    const next = typeof updater === "function" ? updater(sorting) : updater;
    commit({ ...applied, sort: stateToSort(next) });
  };

  const onRun = (filters: FilterClause[]) => commit({ ...applied, filters });

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Screener</h1>
        <p className="text-sm text-muted-foreground">
          Filter the NIFTY 200 by factor scores and fundamentals — share the URL to share the screen.
        </p>
      </header>

      <div className="grid gap-5 lg:grid-cols-[1fr_16rem]">
        <div className="space-y-4">
          <FilterBuilder initialFilters={applied.filters ?? []} onRun={onRun} />

          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              {count == null ? "" : `${count} match${count === 1 ? "" : "es"}`}
            </p>
            <SaveScreenForm criteria={applied} />
          </div>

          {isError ? (
            <p className="py-10 text-center text-sm text-destructive">Could not run the screen.</p>
          ) : (
            <DataTable
              columns={columns}
              data={rows}
              sorting={sorting}
              onSortingChange={onSortingChange}
              emptyMessage={isLoading ? "Running…" : "No stocks match these filters."}
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
        </div>

        <aside className="space-y-2">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Saved screens
          </h2>
          <SavedScreens onLoad={(criteria) => commit(criteria)} />
        </aside>
      </div>

      <CompareTray
        symbols={selected}
        onRemove={(s) => setSelected((prev) => prev.filter((x) => x !== s))}
        onClear={() => setSelected([])}
      />

      <Disclaimer />
    </div>
  );
}

export default function ScreenerPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <ScreenerInner />
    </Suspense>
  );
}

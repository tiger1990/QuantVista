"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type StockListItem = components["schemas"]["StockListItem"];
export type RankingItem = components["schemas"]["RankingItem"];

const PAGE_SIZE = 50;

/** Cursor-paginated stocks (keyset by symbol). Sector filter is server-side; "load more" via cursor. */
export function useStocks(params: { market?: string; sector?: string | null }) {
  const market = params.market ?? "NSE";
  const sector = params.sector ?? undefined;
  return useInfiniteQuery({
    queryKey: ["stocks", market, sector],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/v1/stocks", {
        params: { query: { market, sector, limit: PAGE_SIZE, cursor: pageParam ?? undefined } },
      });
      if (error || !data) throw new Error("Failed to load stocks.");
      return data;
    },
    // meta is a loose dict in the envelope schema; narrow the cursor to keep TPageParam a string.
    getNextPageParam: (last) => (last.meta?.next_cursor as string | null | undefined) ?? null,
  });
}

/** Composite-desc leaderboard (entitlement-capped server-side). */
export function useRankings(params: { market?: string } = {}) {
  const market = params.market ?? "NSE";
  return useQuery({
    queryKey: ["rankings", market],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/rankings", {
        params: { query: { market, limit: PAGE_SIZE } },
      });
      if (error || !data) throw new Error("Failed to load rankings.");
      return data;
    },
  });
}

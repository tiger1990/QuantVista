"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type StockListItem = components["schemas"]["StockListItem"];
export type RankingItem = components["schemas"]["RankingItem"];
export type StockDetail = components["schemas"]["StockDetail"];
export type DecompositionResponse = components["schemas"]["DecompositionResponse"];
export type FactorContribution = components["schemas"]["FactorContribution"];

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

/** Stock master + latest snapshot. Returns `null` on 404 (unknown symbol). */
export function useStockDetail(symbol: string) {
  return useQuery({
    queryKey: ["stock", symbol],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/stocks/{symbol}", {
        params: { path: { symbol } },
      });
      if (response.status === 404) return null;
      if (error || !data) throw new Error("Failed to load stock.");
      return data.data ?? null;
    },
  });
}

/** Per-factor decomposition that sums to the composite (US-02). `null` on 404. */
export function useDecomposition(symbol: string) {
  return useQuery({
    queryKey: ["decomposition", symbol],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/scores/{symbol}/decomposition", {
        params: { path: { symbol } },
      });
      if (response.status === 404) return null;
      if (error || !data) throw new Error("Failed to load decomposition.");
      return data.data ?? null;
    },
  });
}

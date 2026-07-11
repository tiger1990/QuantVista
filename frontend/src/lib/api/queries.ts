"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { ScreenCriteria } from "@/lib/screener";

export type StockListItem = components["schemas"]["StockListItem"];
export type RankingItem = components["schemas"]["RankingItem"];
export type StockDetail = components["schemas"]["StockDetail"];
export type DecompositionResponse = components["schemas"]["DecompositionResponse"];
export type FactorContribution = components["schemas"]["FactorContribution"];
export type ScreenerRow = components["schemas"]["ScreenerRow"];
export type SavedScreen = components["schemas"]["SavedScreen"];
export type NewsItem = components["schemas"]["NewsItem"];

const PAGE_SIZE = 50;
const SCREENER_PAGE_SIZE = 100;

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

/** Query options for one stock's detail — shared by the single and parallel (compare) hooks. */
function stockDetailQuery(symbol: string) {
  return {
    queryKey: ["stock", symbol] as const,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/stocks/{symbol}", {
        params: { path: { symbol } },
      });
      if (response.status === 404) return null;
      if (error || !data) throw new Error("Failed to load stock.");
      return data.data ?? null;
    },
  };
}

/** Stock master + latest snapshot. Returns `null` on 404 (unknown symbol). */
export function useStockDetail(symbol: string) {
  return useQuery(stockDetailQuery(symbol));
}

/** Parallel stock details for the comparison view (QV-040). `null` entries are 404 (skipped). */
export function useCompareDetails(symbols: string[]) {
  return useQueries({
    queries: symbols.map(stockDetailQuery),
    combine: (results) => ({
      isLoading: results.some((r) => r.isLoading),
      isError: results.some((r) => r.isError),
      details: results.map((r) => r.data ?? null),
    }),
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

/**
 * Run a screener criteria against the universe (QV-038). Cursor-paginated (keyset by opaque
 * offset); "load more" via `meta.next_cursor`. Disabled until at least one query mount so an
 * empty screen still fetches the default (composite-desc) page.
 */
export function useScreener(criteria: ScreenCriteria) {
  return useInfiniteQuery({
    queryKey: ["screener", criteria],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.POST("/api/v1/screener", {
        body: {
          universe: "NIFTY200",
          market: criteria.market,
          filters: criteria.filters ?? [],
          sort: criteria.sort ?? null,
          limit: SCREENER_PAGE_SIZE,
          cursor: pageParam ?? null,
        },
      });
      if (error || !data) throw new Error("Failed to run the screen.");
      return data;
    },
    getNextPageParam: (last) => (last.meta?.next_cursor as string | null | undefined) ?? null,
  });
}

/** The tenant's saved screens, newest first (QV-039, RLS-scoped). */
export function useSavedScreens() {
  return useQuery({
    queryKey: ["saved-screens"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/screens");
      if (error || !data) throw new Error("Failed to load saved screens.");
      return data.data ?? [];
    },
  });
}

export type SaveScreenErrorKind = "limit" | "conflict" | "invalid" | "unknown";

/** Typed save failure so the dialog can branch: over-cap → upgrade CTA, dup name, invalid criteria. */
export class SaveScreenError extends Error {
  readonly kind: SaveScreenErrorKind;
  constructor(kind: SaveScreenErrorKind) {
    super(kind);
    this.name = "SaveScreenError";
    this.kind = kind;
  }
}

function saveErrorKind(status: number): SaveScreenErrorKind {
  if (status === 403) return "limit";
  if (status === 409) return "conflict";
  if (status === 422) return "invalid";
  return "unknown";
}

/** Save the current criteria as a named screen; invalidates the saved list on success. */
export function useSaveScreen() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { name: string; criteria: ScreenCriteria }) => {
      const { data, error, response } = await api.POST("/api/v1/screens", {
        body: { name: vars.name, criteria: vars.criteria },
      });
      if (error || !data) throw new SaveScreenError(saveErrorKind(response.status));
      return data.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-screens"] }),
  });
}

/** Recent news tagged to a stock (QV-043), history-windowed by the plan. */
export function useStockNews(symbol: string) {
  return useQuery({
    queryKey: ["stock-news", symbol],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/stocks/{symbol}/news", {
        params: { path: { symbol }, query: { limit: 20 } },
      });
      if (error || !data) throw new Error("Failed to load news.");
      return data.data ?? [];
    },
  });
}

/** Market-wide latest news (India-source-first), for the News page + Overview ticker. */
export function useLatestNews(limit = 30) {
  return useQuery({
    queryKey: ["latest-news", limit],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/news", { params: { query: { limit } } });
      if (error || !data) throw new Error("Failed to load news.");
      return data.data ?? [];
    },
  });
}

/** Delete a saved screen by id; invalidates the saved list on success. */
export function useDeleteScreen() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE("/api/v1/screens/{screen_id}", {
        params: { path: { screen_id: id } },
      });
      if (error) throw new Error("Failed to delete the screen.");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-screens"] }),
  });
}

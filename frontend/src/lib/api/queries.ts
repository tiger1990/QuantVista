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
export type AlertRule = components["schemas"]["AlertRule"];
export type CreateAlertRequest = components["schemas"]["CreateAlertRequest"];
export type NotificationItem = components["schemas"]["Notification"];
export type Portfolio = components["schemas"]["Portfolio"];
export type Position = components["schemas"]["Position"];
export type UpsertPositionRequest = components["schemas"]["UpsertPositionRequest"];
export type OptimizeRequest = components["schemas"]["OptimizeRequest"];
export type OptimizeConstraints = components["schemas"]["OptimizeConstraints"];
export type OptimizeResponse = components["schemas"]["OptimizeResponse"];
export type ConstraintStatusDTO = components["schemas"]["ConstraintStatusDTO"];

const PAGE_SIZE = 50;
const SCREENER_PAGE_SIZE = 100;

/** Cursor-paginated stocks (keyset by symbol). Sector + search filters are server-side (whole
 * universe, not just loaded pages); "load more" via cursor. */
export function useStocks(params: { market?: string; sector?: string | null; q?: string | null }) {
  const market = params.market ?? "NSE";
  const sector = params.sector ?? undefined;
  const q = params.q?.trim() || undefined;
  return useInfiniteQuery({
    queryKey: ["stocks", market, sector, q],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/v1/stocks", {
        params: { query: { market, sector, q, limit: PAGE_SIZE, cursor: pageParam ?? undefined } },
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

// --- Alerts (QV-047 API / QV-050 UI), RLS-scoped to the user's own rules --------------------
/** The user's alert rules. */
export function useAlerts() {
  return useQuery({
    queryKey: ["alerts"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/alerts");
      if (error || !data) throw new Error("Failed to load alerts.");
      return data.data ?? [];
    },
  });
}

export type CreateAlertErrorKind = "limit" | "invalid" | "unknown";

/** Typed create failure so the form can branch: over-cap (403) → upgrade CTA, invalid (422). */
export class CreateAlertError extends Error {
  readonly kind: CreateAlertErrorKind;
  constructor(kind: CreateAlertErrorKind) {
    super(kind);
    this.name = "CreateAlertError";
    this.kind = kind;
  }
}

/** Create an alert rule; invalidates the list on success. */
export function useCreateAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: CreateAlertRequest) => {
      const { data, error, response } = await api.POST("/api/v1/alerts", { body: vars });
      if (error || !data) {
        const kind: CreateAlertErrorKind =
          response.status === 403 ? "limit" : response.status === 422 ? "invalid" : "unknown";
        throw new CreateAlertError(kind);
      }
      return data.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
}

/** Delete an alert rule by id; invalidates the list on success. */
export function useDeleteAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE("/api/v1/alerts/{rule_id}", {
        params: { path: { rule_id: id } },
      });
      if (error) throw new Error("Failed to delete the alert.");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
}

// --- Notifications (QV-050): the in-app center feed -----------------------------------------
/** The user's recent notifications; polled so the bell stays fresh. */
export function useNotifications() {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/notifications", {
        params: { query: { limit: 20 } },
      });
      if (error || !data) throw new Error("Failed to load notifications.");
      return data.data ?? [];
    },
    refetchInterval: 60_000,
  });
}

/** Mark all of the user's notifications read; invalidates the feed on success. */
export function useMarkNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/api/v1/notifications/read", {});
      if (error) throw new Error("Failed to mark notifications read.");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

// --- Portfolios (QV-052 CRUD / QV-055 optimize), RLS-scoped, entitlement-gated --------------

/** Read the standard envelope's `error.message` off a non-2xx openapi-fetch error body. */
function envelopeMessage(error: unknown): string | undefined {
  const err = error as { error?: { message?: string } } | undefined;
  return err?.error?.message;
}

/** The tenant's portfolios, newest first. */
export function usePortfolios() {
  return useQuery({
    queryKey: ["portfolios"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/portfolios");
      if (error || !data) throw new Error("Failed to load portfolios.");
      return data.data ?? [];
    },
  });
}

/** A single portfolio by id (404 → thrown). */
export function usePortfolio(id: string) {
  return useQuery({
    queryKey: ["portfolio", id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/portfolios/{portfolio_id}", {
        params: { path: { portfolio_id: id } },
      });
      if (error || !data) throw new Error("Failed to load portfolio.");
      return data.data;
    },
    enabled: Boolean(id),
  });
}

export type CreatePortfolioErrorKind = "limit" | "invalid" | "unknown";

/** Typed create failure so the form can branch: over-cap (403) → upgrade CTA, invalid (422). */
export class CreatePortfolioError extends Error {
  readonly kind: CreatePortfolioErrorKind;
  constructor(kind: CreatePortfolioErrorKind) {
    super(kind);
    this.name = "CreatePortfolioError";
    this.kind = kind;
  }
}

/** Create a portfolio; invalidates the list on success. */
export function useCreatePortfolio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { name: string }) => {
      const { data, error, response } = await api.POST("/api/v1/portfolios", {
        body: { name: vars.name, benchmark: "NIFTY200_TRI", base_currency: "INR" },
      });
      if (error || !data) {
        const kind: CreatePortfolioErrorKind =
          response.status === 403 ? "limit" : response.status === 422 ? "invalid" : "unknown";
        throw new CreatePortfolioError(kind);
      }
      return data.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolios"] }),
  });
}

/** Delete a portfolio by id; invalidates the list on success. */
export function useDeletePortfolio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error } = await api.DELETE("/api/v1/portfolios/{portfolio_id}", {
        params: { path: { portfolio_id: id } },
      });
      if (error) throw new Error("Failed to delete the portfolio.");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolios"] }),
  });
}

/** The portfolio's positions. */
export function usePositions(portfolioId: string) {
  return useQuery({
    queryKey: ["positions", portfolioId],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/portfolios/{portfolio_id}/positions", {
        params: { path: { portfolio_id: portfolioId } },
      });
      if (error || !data) throw new Error("Failed to load positions.");
      return data.data ?? [];
    },
    enabled: Boolean(portfolioId),
  });
}

/** Upsert a position (weight/shares/etc.) under a portfolio; invalidates positions on success. */
export function useUpsertPosition(portfolioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { stockId: string; body: UpsertPositionRequest }) => {
      const { data, error } = await api.PUT(
        "/api/v1/portfolios/{portfolio_id}/positions/{stock_id}",
        { params: { path: { portfolio_id: portfolioId, stock_id: vars.stockId } }, body: vars.body },
      );
      if (error || !data) throw new Error("Failed to save the holding.");
      return data.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["positions", portfolioId] }),
  });
}

/** Remove a holding from a portfolio; invalidates positions on success. */
export function useDeletePosition(portfolioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (stockId: string) => {
      const { error } = await api.DELETE(
        "/api/v1/portfolios/{portfolio_id}/positions/{stock_id}",
        { params: { path: { portfolio_id: portfolioId, stock_id: stockId } } },
      );
      if (error) throw new Error("Failed to remove the holding.");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["positions", portfolioId] }),
  });
}

export type OptimizeErrorKind = "limit" | "infeasible" | "invalid" | "unknown";

/** Typed optimize failure: 403 → upgrade CTA, `infeasible` (422) carries the binding-constraint
 * message, other 422 → invalid. */
export class OptimizeError extends Error {
  readonly kind: OptimizeErrorKind;
  readonly detail?: string;
  constructor(kind: OptimizeErrorKind, detail?: string) {
    super(detail ?? kind);
    this.name = "OptimizeError";
    this.kind = kind;
    this.detail = detail;
  }
}

/** Optimize a portfolio's allocation. Returns weights + metrics + per-constraint status; an
 * infeasible problem surfaces the binding constraint (US-03), a Free-tier caller gets a 403. */
export function useOptimize(portfolioId: string) {
  return useMutation({
    mutationFn: async (vars: OptimizeRequest) => {
      const { data, error, response } = await api.POST(
        "/api/v1/portfolios/{portfolio_id}/optimize",
        { params: { path: { portfolio_id: portfolioId } }, body: vars },
      );
      if (error || !data) {
        const message = envelopeMessage(error);
        const code = (error as { error?: { code?: string } } | undefined)?.error?.code;
        const kind: OptimizeErrorKind =
          response.status === 403
            ? "limit"
            : code === "infeasible"
              ? "infeasible"
              : response.status === 422
                ? "invalid"
                : "unknown";
        throw new OptimizeError(kind, message);
      }
      return data.data;
    },
  });
}

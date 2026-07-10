/**
 * Screener allow-list catalog + URL codec (QV-040, client mirror of backend `analytics/screener.py`).
 *
 * The mirror is a UX affordance — the builder only offers valid field/op pairs — but the server
 * re-validates every request, so callers must still handle 422. The URL codec makes a screen
 * shareable: `{ market, filters, sort }` ⇆ compact search params, decoding defensively so a
 * hand-edited link never white-screens.
 */
import type { components } from "@/lib/api/schema";

export type FilterClause = components["schemas"]["FilterClause"];
export type ScreenCriteria = components["schemas"]["ScreenCriteria"];

/** UX cap on the side-by-side comparison — not an entitlement (none is seeded). */
export const COMPARE_MAX = 4;
export const DEFAULT_MARKET = "NSE";
export const DEFAULT_SORT = "-composite_score";

/** Numeric fields → display label (mirrors backend `FIELDS`). Support all `NUMERIC_OPS`. */
export const NUMERIC_FIELDS = {
  composite_score: "Composite",
  fundamental_score: "Fundamental",
  momentum_score: "Momentum",
  quality_score: "Quality",
  sentiment_score: "Sentiment",
  risk_score: "Risk",
  coverage: "Coverage",
  pe: "P/E",
  pb: "P/B",
  roe: "ROE",
  roce: "ROCE",
  debt_equity: "D/E",
} as const;

/** Categorical fields → display label (mirrors backend `CATEGORICAL`). Support `eq` only. */
export const CATEGORICAL_FIELDS = {
  sector: "Sector",
  market_cap_bucket: "Market cap",
} as const;

/** Numeric operators → symbol (mirrors backend `NUMERIC_OPS`). */
export const NUMERIC_OPS = {
  gte: "≥",
  lte: "≤",
  gt: ">",
  lt: "<",
  eq: "=",
} as const;

export type NumericField = keyof typeof NUMERIC_FIELDS;
export type CategoricalField = keyof typeof CATEGORICAL_FIELDS;
export type NumericOp = keyof typeof NUMERIC_OPS;

/** Sortable fields = every numeric field plus `symbol` (mirrors backend `SORT_FIELDS`). */
export const SORT_FIELDS: readonly string[] = [...Object.keys(NUMERIC_FIELDS), "symbol"];

const isNumericField = (f: string): f is NumericField => f in NUMERIC_FIELDS;
const isCategoricalField = (f: string): f is CategoricalField => f in CATEGORICAL_FIELDS;
const isNumericOp = (op: string): op is NumericOp => op in NUMERIC_OPS;

/**
 * Validate one clause against the allow-list, returning a normalized `FilterClause` or `null`.
 * Numeric fields coerce the value to a number; categorical fields accept a trimmed non-empty
 * string under `eq` only. Unknown field/op → `null` (the injection guard, client-side).
 */
export function validateClause(
  field: string,
  op: string,
  value: string | number,
): FilterClause | null {
  if (isNumericField(field)) {
    if (!isNumericOp(op)) return null;
    const num = typeof value === "number" ? value : Number.parseFloat(value);
    if (Number.isNaN(num)) return null;
    return { field, op, value: num };
  }
  if (isCategoricalField(field)) {
    if (op !== "eq") return null;
    const s = String(value).trim();
    if (!s) return null;
    return { field, op, value: s };
  }
  return null;
}

/** Normalize a sort spec to an allow-listed one, falling back to the composite-desc default. */
export function validateSort(sort: string | null | undefined): string {
  if (!sort) return DEFAULT_SORT;
  const descending = sort.startsWith("-");
  const name = descending ? sort.slice(1) : sort;
  return SORT_FIELDS.includes(name) ? sort : DEFAULT_SORT;
}

/** Compact filter encoding: `field:op:value` clauses joined by `;`. */
export function encodeFilters(filters: readonly FilterClause[]): string {
  return filters.map((c) => `${c.field}:${c.op}:${c.value}`).join(";");
}

/** Parse the compact filter string, dropping any clause outside the allow-list. */
export function decodeFilters(raw: string | null | undefined): FilterClause[] {
  if (!raw) return [];
  return raw
    .split(";")
    .map((part) => {
      const [field, op, ...rest] = part.split(":");
      return validateClause(field ?? "", op ?? "", rest.join(":"));
    })
    .filter((c): c is FilterClause => c !== null);
}

/** Criteria → search-param object, omitting defaults so shared links stay short. */
export function encodeCriteria(criteria: ScreenCriteria): Record<string, string> {
  const out: Record<string, string> = {};
  if (criteria.market && criteria.market !== DEFAULT_MARKET) out.market = criteria.market;
  const filters = encodeFilters(criteria.filters ?? []);
  if (filters) out.f = filters;
  const sort = criteria.sort ?? DEFAULT_SORT;
  if (sort !== DEFAULT_SORT) out.sort = sort;
  return out;
}

/** Search params → normalized criteria (defensive: unknown fields/ops are dropped). */
export function decodeCriteria(params: URLSearchParams): ScreenCriteria {
  return {
    market: params.get("market") || DEFAULT_MARKET,
    filters: decodeFilters(params.get("f")),
    sort: validateSort(params.get("sort")),
  };
}

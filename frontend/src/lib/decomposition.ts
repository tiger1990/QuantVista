import type { FactorContribution } from "@/lib/api/queries";

export interface CategoryGroup {
  category: string;
  factors: FactorContribution[];
  total: number; // summed contribution for the category
}

/** Group factor contributions by category (per-category totals), ordered by total desc. */
export function groupByCategory(factors: FactorContribution[]): CategoryGroup[] {
  const map = new Map<string, FactorContribution[]>();
  for (const f of factors) {
    const list = map.get(f.category) ?? [];
    list.push(f);
    map.set(f.category, list);
  }
  return [...map.entries()]
    .map(([category, fs]) => ({
      category,
      factors: fs,
      total: fs.reduce((acc, f) => acc + f.contribution, 0),
    }))
    .sort((a, b) => b.total - a.total);
}

/** Whether the contributions reconcile to the composite (± tolerance) — the US-02 invariant. */
export function sumsToComposite(sum: number, composite: number, tolerance = 0.01): boolean {
  return Math.abs(sum - composite) <= tolerance;
}

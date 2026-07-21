"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Position } from "@/lib/api/queries";

/** Parse a Decimal-string weight to a percentage number for display (chart math only). */
function pct(value: string | number | null | undefined): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? Math.round(n * 1000) / 10 : 0;
}

const EPSILON = 0.0001;

/** Grouped bars: each stock's current (or equal-weight) allocation vs the optimized weight (%).
 * Freshly-added holdings have no target weight, so when nothing is set we compare against an
 * equal-weight baseline (1/N) rather than a misleading row of zeros. */
export function WeightsChart({
  positions,
  optimized,
}: {
  positions: Position[];
  optimized: Record<string, string> | null;
}) {
  const ids = Array.from(
    new Set([...positions.map((p) => p.stock_id), ...Object.keys(optimized ?? {})]),
  );
  if (ids.length === 0) return null;

  const symbolByStock = new Map(positions.map((p) => [p.stock_id, p.symbol]));
  const currentByStock = new Map(positions.map((p) => [p.stock_id, p.target_weight]));

  const currentTotal = positions.reduce((sum, p) => sum + Number(p.target_weight ?? 0), 0);
  const useEqualWeight = currentTotal < EPSILON;
  const equalWeight = positions.length > 0 ? 1 / positions.length : 0;
  const currentLabel = useEqualWeight ? "Equal weight" : "Current";

  const data = ids.map((id) => ({
    symbol: symbolByStock.get(id) ?? id.slice(0, 8),
    current: useEqualWeight ? pct(equalWeight) : pct(currentByStock.get(id)),
    optimized: pct(optimized?.[id]),
  }));

  return (
    <div className="h-64 w-full" aria-label="Optimized weights vs current allocation">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis
            dataKey="symbol"
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            interval={0}
            angle={-30}
            textAnchor="end"
            height={50}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            unit="%"
            width={44}
          />
          <Tooltip
            cursor={{ fill: "var(--color-muted)", opacity: 0.4 }}
            contentStyle={{
              background: "var(--color-popover)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--color-popover-foreground)",
            }}
            labelStyle={{ color: "var(--color-foreground)", fontWeight: 500 }}
            itemStyle={{ color: "var(--color-popover-foreground)" }}
            formatter={(v) => `${v}%`}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="current" name={currentLabel} fill="var(--color-muted-foreground)" radius={[2, 2, 0, 0]} />
          <Bar dataKey="optimized" name="Optimized" fill="var(--color-primary)" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

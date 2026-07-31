"use client";

import { memo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { EquityPoint } from "./lib";

/** The tearsheet hero: strategy (solid accent) vs benchmark (muted, dashed) equity over time.
 * Sampled at rebalance dates (QV-071); memoized so sibling updates can't re-flash it. */
export const EquityCurveChart = memo(function EquityCurveChart({ data }: { data: EquityPoint[] }) {
  if (data.length < 2) {
    return (
      <p className="text-sm text-muted-foreground">Not enough history to plot an equity curve.</p>
    );
  }
  return (
    <div className="h-72 w-full" aria-label="Strategy equity vs benchmark over time">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
            minTickGap={40}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            width={48}
            domain={["auto", "auto"]}
            tickFormatter={(v: number) => v.toFixed(2)}
          />
          <Tooltip
            contentStyle={{
              background: "var(--color-popover)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--color-popover-foreground)",
            }}
            labelStyle={{ color: "var(--color-foreground)", fontWeight: 500 }}
            formatter={(v) => (typeof v === "number" ? v.toFixed(3) : String(v))}
          />
          <Line
            type="monotone"
            dataKey="strategy"
            name="Strategy"
            stroke="var(--color-primary)"
            strokeWidth={1.75}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="benchmark"
            name="Nifty 200"
            stroke="var(--color-muted-foreground)"
            strokeWidth={1.25}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
});

"use client";

import { memo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { sectorChartData } from "@/lib/risk";

/** Portfolio weight by sector (%), sorted descending. Memoized: the `exposure` prop is
 * referentially stable across parent re-renders (TanStack Query structural sharing), so a sibling
 * update (e.g. a rebalance check) won't re-render/re-flash this chart. */
export const SectorExposureChart = memo(function SectorExposureChart({
  exposure,
}: {
  exposure: Record<string, string>;
}) {
  const data = sectorChartData(exposure);
  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">No sector exposure.</p>;
  }
  return (
    <div className="h-72 w-full" aria-label="Portfolio weight by sector">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 24, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis
            dataKey="sector"
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            interval={0}
            angle={-30}
            textAnchor="end"
            height={72}
            tickMargin={8}
          />
          <YAxis tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }} unit="%" width={44} />
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
          <Bar
            dataKey="pct"
            name="Weight"
            fill="var(--color-primary)"
            radius={[2, 2, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
});

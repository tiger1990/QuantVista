"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DrawdownPointDTO } from "@/lib/api/queries";
import { drawdownChartData } from "@/lib/risk";

/** Drawdown-over-time: the portfolio's decline from its running equity peak (%, ≤ 0). */
export function DrawdownChart({ series }: { series: DrawdownPointDTO[] }) {
  const data = drawdownChartData(series);
  if (data.length < 2) {
    return <p className="text-sm text-muted-foreground">Not enough history for a drawdown chart.</p>;
  }
  return (
    <div className="h-56 w-full" aria-label="Portfolio drawdown over time">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: -8 }}>
          <defs>
            <linearGradient id="drawdownFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-destructive)" stopOpacity={0.05} />
              <stop offset="100%" stopColor="var(--color-destructive)" stopOpacity={0.35} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
            minTickGap={32}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            unit="%"
            width={44}
            domain={["dataMin", 0]}
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
            itemStyle={{ color: "var(--color-popover-foreground)" }}
            formatter={(v) => `${v}%`}
          />
          <Area
            type="monotone"
            dataKey="pct"
            name="Drawdown"
            stroke="var(--color-destructive)"
            fill="url(#drawdownFill)"
            strokeWidth={1.5}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

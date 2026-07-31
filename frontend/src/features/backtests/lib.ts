/**
 * Pure helpers for the backtest tearsheet (QV-071): tier derivation, Decimal-safe formatting,
 * preset ranges, metric grouping, and the equity-curve chart shape. No React — unit-tested directly.
 * Money/ratios arrive as Decimal strings; we `Number()` only here at the render boundary.
 */

export type Tier = "free" | "pro" | "quant";
type Entitlements = Record<string, number | boolean | null> | undefined;

/** Free (no `backtest`) · Pro (`backtest`, no `backtest_full`) · Quant (`backtest_full`). */
export function tierFrom(entitlements: Entitlements): Tier {
  if (entitlements?.backtest_full) return "quant";
  if (entitlements?.backtest) return "pro";
  return "free";
}

const num = (v: unknown): number => {
  const n = typeof v === "string" ? Number(v) : typeof v === "number" ? v : NaN;
  return Number.isFinite(n) ? n : 0;
};

/** "12.34%" from a fraction Decimal string (0.1234). */
export function fmtPct(v: unknown, digits = 2): string {
  return `${(num(v) * 100).toFixed(digits)}%`;
}

/** "1.23" ratio (Sharpe/Sortino/beta/IR). */
export function fmtRatio(v: unknown, digits = 2): string {
  return num(v).toFixed(digits);
}

export type Sign = "pos" | "neg" | "zero";
export function signOf(v: unknown): Sign {
  const n = num(v);
  return n > 0 ? "pos" : n < 0 ? "neg" : "zero";
}

export const PRESETS: { label: string; months: number }[] = [
  { label: "3M", months: 3 },
  { label: "6M", months: 6 },
  { label: "1Y", months: 12 },
];

/** ISO `{start, end}` for a trailing preset window ending today (Pro is capped at 1Y). */
export function presetRange(months: number, today = new Date()): { start: string; end: string } {
  const end = new Date(today);
  const start = new Date(today);
  start.setMonth(start.getMonth() - months);
  const iso = (d: Date): string => d.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(end) };
}

/** Days between two ISO dates (for the Pro ≤1y client guard; server is the backstop). */
export function rangeDays(start: string, end: string): number {
  return Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000);
}

export type MetricRow = { label: string; value: string; sign?: Sign };
export type MetricGroup = { title: string; rows: MetricRow[] };

/** The QV-068 suite grouped for the factsheet block (Return · Risk · vs Benchmark · Activity). */
export function metricGroups(m: Record<string, unknown>): MetricGroup[] {
  return [
    {
      title: "Return",
      rows: [
        { label: "Total return", value: fmtPct(m.total_return), sign: signOf(m.total_return) },
        { label: "CAGR", value: fmtPct(m.cagr), sign: signOf(m.cagr) },
        { label: "Hit rate", value: fmtPct(m.hit_rate) },
      ],
    },
    {
      title: "Risk",
      rows: [
        { label: "Ann. volatility", value: fmtPct(m.ann_vol) },
        { label: "Max drawdown", value: fmtPct(m.max_drawdown), sign: signOf(m.max_drawdown) },
        { label: "Sharpe", value: fmtRatio(m.sharpe) },
        { label: "Sortino", value: fmtRatio(m.sortino) },
      ],
    },
    {
      title: "vs Benchmark",
      rows: [
        { label: "Benchmark", value: fmtPct(m.benchmark_return), sign: signOf(m.benchmark_return) },
        { label: "Excess", value: fmtPct(m.excess_return), sign: signOf(m.excess_return) },
        { label: "Beta", value: fmtRatio(m.beta) },
        { label: "Tracking error", value: fmtPct(m.tracking_error) },
        { label: "Information ratio", value: fmtRatio(m.information_ratio) },
      ],
    },
    {
      title: "Activity",
      rows: [
        { label: "Avg turnover", value: fmtPct(m.avg_turnover) },
        { label: "Avg exposure", value: fmtPct(m.avg_exposure) },
        { label: "Rebalances", value: String(m.n_rebalances ?? 0) },
      ],
    },
  ];
}

export type EquityPoint = { date: string; strategy: number; benchmark: number };

/** The recharts series from `metrics.equity_curve` (Decimal strings → numbers). */
export function equityChartData(m: Record<string, unknown>): EquityPoint[] {
  const raw = Array.isArray(m.equity_curve) ? (m.equity_curve as Record<string, string>[]) : [];
  return raw.map((p) => ({
    date: p.as_of,
    strategy: num(p.strategy),
    benchmark: num(p.benchmark),
  }));
}

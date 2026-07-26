import type { DrawdownPointDTO } from "@/lib/api/queries";

const DASH = "—";

/** Format a Decimal-string fraction as a percentage (e.g. "0.1234" → "12.34%"); null → em dash. */
export function fmtPct(value: string | null | undefined, digits = 2): string {
  if (value == null) return DASH;
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : DASH;
}

/** Format a Decimal-string plain number to fixed digits (beta/Sharpe/Sortino/HHI); null → em dash. */
export function fmtNum(value: string | null | undefined, digits = 2): string {
  if (value == null) return DASH;
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : DASH;
}

/** sector → Decimal-string weight → chart rows in percentage points, sorted descending by weight. */
export function sectorChartData(exposure: Record<string, string>): { sector: string; pct: number }[] {
  return Object.entries(exposure)
    .map(([sector, w]) => ({ sector, pct: Math.round(Number(w) * 1000) / 10 }))
    .sort((a, b) => b.pct - a.pct);
}

/** Dated drawdown series → chart rows in percentage points (≤ 0), preserving chronological order. */
export function drawdownChartData(series: DrawdownPointDTO[]): { date: string; pct: number }[] {
  return series.map((p) => ({ date: p.date, pct: Math.round(Number(p.value) * 1000) / 10 }));
}

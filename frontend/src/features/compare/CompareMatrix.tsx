"use client";

import Link from "next/link";

import type { StockDetail } from "@/lib/api/queries";
import { formatScore, scoreTone, toneTextClass } from "@/lib/score";

type Snapshot = StockDetail["snapshot"];

interface Row {
  label: string;
  get: (s: Snapshot) => number | null;
  kind: "score" | "metric";
}

// Rows = composite + the five sub-scores (toned heatmap), then key fundamentals.
const SCORE_ROWS: Row[] = [
  { label: "Composite", get: (s) => s.composite_score, kind: "score" },
  { label: "Fundamental", get: (s) => s.fundamental_score, kind: "score" },
  { label: "Momentum", get: (s) => s.momentum_score, kind: "score" },
  { label: "Quality", get: (s) => s.quality_score, kind: "score" },
  { label: "Sentiment", get: (s) => s.sentiment_score, kind: "score" },
  { label: "Risk", get: (s) => s.risk_score, kind: "score" },
];
const METRIC_ROWS: Row[] = [
  { label: "P/E", get: (s) => s.pe, kind: "metric" },
  { label: "P/B", get: (s) => s.pb, kind: "metric" },
  { label: "ROE", get: (s) => s.roe, kind: "metric" },
  { label: "ROCE", get: (s) => s.roce, kind: "metric" },
  { label: "D/E", get: (s) => s.debt_equity, kind: "metric" },
];

function Cell({ row, snapshot }: { row: Row; snapshot: Snapshot }) {
  const value = row.get(snapshot);
  if (row.kind === "score") {
    return (
      <td className={`px-4 py-2 text-right tabular-nums ${toneTextClass(scoreTone(value))}`}>
        {formatScore(value)}
      </td>
    );
  }
  return (
    <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
      {value == null ? "—" : value.toFixed(2)}
    </td>
  );
}

/** Side-by-side matrix: stocks as columns, factor scores + fundamentals as rows. */
export function CompareMatrix({ details }: { details: StockDetail[] }) {
  const rowGroup = (rows: Row[], caption: string) => (
    <>
      <tr className="border-t border-border">
        <th
          colSpan={details.length + 1}
          className="px-4 py-1.5 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground"
        >
          {caption}
        </th>
      </tr>
      {rows.map((row) => (
        <tr key={row.label} className="border-t border-border/60">
          <th scope="row" className="px-4 py-2 text-left text-sm font-normal text-muted-foreground">
            {row.label}
          </th>
          {details.map((d) => (
            <Cell key={d.symbol} row={row} snapshot={d.snapshot} />
          ))}
        </tr>
      ))}
    </>
  );

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="px-4 py-3 text-left" />
            {details.map((d) => (
              <th key={d.symbol} className="px-4 py-3">
                <div className="flex flex-col items-end">
                  <Link
                    href={`/stocks/${d.symbol}`}
                    className="font-semibold hover:text-primary hover:underline"
                  >
                    {d.symbol}
                  </Link>
                  <span className="max-w-32 truncate text-xs font-normal text-muted-foreground">
                    {d.company_name}
                  </span>
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowGroup(SCORE_ROWS, "Factor scores")}
          {rowGroup(METRIC_ROWS, "Fundamentals")}
        </tbody>
      </table>
    </div>
  );
}

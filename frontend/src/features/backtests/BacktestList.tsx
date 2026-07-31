"use client";

import type { BacktestListItem } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const statusClass: Record<string, string> = {
  succeeded: "text-[var(--color-positive)]",
  failed: "text-destructive",
  running: "text-foreground",
  queued: "text-muted-foreground",
};

/** Past runs — a compact analyst ledger (status · range · submitted), hairline-separated. Each row
 * opens that run's tearsheet: rows are buttons, not decoration, so a finished run is reviewable
 * without re-running it. */
export function BacktestList({
  items,
  selectedId,
  onSelect,
}: {
  items: BacktestListItem[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
}) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No backtests yet.</p>;
  }
  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {items.map((b) => (
        <button
          key={b.id}
          type="button"
          onClick={() => onSelect(b.id)}
          aria-current={b.id === selectedId ? "true" : undefined}
          className={cn(
            "flex w-full items-center justify-between gap-4 px-4 py-2.5 text-left text-sm",
            "transition-colors hover:bg-muted/50 focus-visible:outline-none",
            "focus-visible:ring-1 focus-visible:ring-ring",
            b.id === selectedId && "bg-muted/60",
          )}
        >
          <span
            className={cn("w-20 font-mono text-xs uppercase tracking-wide", statusClass[b.status])}
          >
            {b.status}
          </span>
          <span className="flex-1 tabular-nums text-muted-foreground">
            {b.start} → {b.end}
          </span>
          <span className="tabular-nums text-xs text-muted-foreground">
            {b.created_at.slice(0, 10)}
          </span>
        </button>
      ))}
    </div>
  );
}

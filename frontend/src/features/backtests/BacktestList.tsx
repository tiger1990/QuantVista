"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";

import type { BacktestListItem } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const statusClass: Record<string, string> = {
  succeeded: "text-[var(--color-positive)]",
  failed: "text-destructive",
  running: "text-foreground",
  queued: "text-muted-foreground",
};

/** Past runs — a compact analyst ledger (status · range · submitted), hairline-separated. Each row
 * opens that run's tearsheet, and carries its own delete with an inline confirm (a rule, not a
 * modal — the tearsheet's editorial register). Deleting is irreversible, so it always asks. */
export function BacktestList({
  items,
  selectedId,
  onSelect,
  onDelete,
  deletingId,
}: {
  items: BacktestListItem[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
  onDelete?: (id: string) => void;
  deletingId?: string | null;
}) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No backtests yet.</p>;
  }
  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {items.map((b) => {
        const isConfirming = confirmingId === b.id;
        const isDeleting = deletingId === b.id;
        return (
          <div
            key={b.id}
            className={cn(
              "flex items-center gap-2 pr-2 text-sm transition-colors",
              b.id === selectedId && "bg-muted/60",
              isDeleting && "opacity-50",
            )}
          >
            <button
              type="button"
              onClick={() => onSelect(b.id)}
              aria-current={b.id === selectedId ? "true" : undefined}
              disabled={isDeleting}
              className={cn(
                "flex flex-1 items-center justify-between gap-4 px-4 py-2.5 text-left",
                "transition-colors hover:bg-muted/50 focus-visible:outline-none",
                "focus-visible:ring-1 focus-visible:ring-ring",
              )}
            >
              <span
                className={cn(
                  "w-20 font-mono text-xs uppercase tracking-wide",
                  statusClass[b.status],
                )}
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

            {onDelete == null ? null : isConfirming ? (
              <span className="flex shrink-0 items-center gap-1.5 text-xs">
                <span className="text-muted-foreground">Delete?</span>
                <button
                  type="button"
                  onClick={() => {
                    setConfirmingId(null);
                    onDelete(b.id);
                  }}
                  className="rounded-sm px-1.5 py-0.5 font-medium text-destructive hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  Delete
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmingId(null)}
                  className="rounded-sm px-1.5 py-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                aria-label={`Delete backtest ${b.start} to ${b.end}`}
                onClick={() => setConfirmingId(b.id)}
                disabled={isDeleting}
                className={cn(
                  "shrink-0 rounded-md border border-border p-1.5 text-muted-foreground",
                  "transition-colors hover:border-destructive/40 hover:text-destructive",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  "disabled:pointer-events-none disabled:opacity-50",
                )}
              >
                <Trash2 className="size-4" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

"use client";

import { DeleteButton } from "@/components/delete-button";
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
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No backtests yet.</p>;
  }
  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {items.map((b) => {
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

            {onDelete == null ? null : (
              <DeleteButton
                label={`Delete backtest ${b.start} to ${b.end}`}
                pending={isDeleting}
                onConfirm={() => onDelete(b.id)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

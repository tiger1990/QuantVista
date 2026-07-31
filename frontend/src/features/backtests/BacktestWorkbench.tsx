"use client";

import { useBacktest } from "@/lib/api/queries";

import { BacktestResults } from "./BacktestResults";
import { BacktestSetupForm } from "./BacktestSetupForm";
import type { Tier } from "./lib";

/** Orchestrates one run: submit → poll (queued/running) → results | failure. Coarse progress
 * (fine-grained % is out of scope, QV-065). The active run id is owned by the URL (see
 * `useSelectedRun`) so the tearsheet survives a refresh and history rows can open a past run. */
export function BacktestWorkbench({
  tier,
  activeId,
  onSelect,
}: {
  tier: Tier;
  activeId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const poll = useBacktest(activeId);
  const bt = poll.data;

  return (
    <div className="space-y-5">
      <BacktestSetupForm tier={tier} onQueued={onSelect} />

      {activeId == null ? null : poll.isError ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-card p-5 text-sm text-destructive"
        >
          Could not load that backtest.
        </div>
      ) : bt?.status === "succeeded" ? (
        <BacktestResults backtest={bt} />
      ) : bt?.status === "failed" ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-card p-5 text-sm text-destructive"
        >
          Backtest failed{bt.error ? `: ${bt.error}` : "."}
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-5 text-sm text-muted-foreground">
          <span
            className="size-3 animate-spin rounded-full border-2 border-muted-foreground/40 border-t-foreground"
            aria-hidden
          />
          Running your backtest… <span className="font-mono">{bt?.status ?? "queued"}</span>
        </div>
      )}
    </div>
  );
}

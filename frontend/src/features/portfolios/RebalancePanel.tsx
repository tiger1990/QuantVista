"use client";

import { useState } from "react";

import { Disclaimer } from "@/components/disclaimer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  RebalanceError,
  type RebalanceResponse,
  useApplyTargets,
  useRebalance,
} from "@/lib/api/queries";
import { fmtPct } from "@/lib/risk";
import { cn } from "@/lib/utils";

/** Drift check → suggested buy/sell trades to reach target weights, with an apply-to-targets action
 * that persists the plan's normalized targets. Read-only research signal (not advice). */
export function RebalancePanel({
  portfolioId,
  hasHoldings,
}: {
  portfolioId: string;
  hasHoldings: boolean;
}) {
  const [threshold, setThreshold] = useState("0.05");
  // Hold the last plan in local state so a re-check UPDATES the result card in place instead of
  // unmounting it (the mutation resets `data` to undefined while pending → the card would collapse
  // and remount, flickering the page as its height toggles the scrollbar).
  const [plan, setPlan] = useState<RebalanceResponse | null>(null);
  const [err, setErr] = useState<RebalanceError | null>(null);
  const rebalance = useRebalance(portfolioId);
  const applyTargets = useApplyTargets(portfolioId);

  const check = () =>
    rebalance.mutate(threshold.trim() || "0.05", {
      onSuccess: (data) => {
        setPlan(data);
        setErr(null);
      },
      onError: (e) => {
        setPlan(null);
        setErr(e instanceof RebalanceError ? e : new RebalanceError("unknown"));
      },
    });

  const apply = () => {
    if (!plan || plan.trades.length === 0) return;
    if (!window.confirm("Apply these target weights to your holdings?")) return;
    applyTargets.mutate(
      plan.trades.map((t) => ({ stock_id: t.stock_id, target_weight: t.target_weight })),
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="drift-threshold">Drift threshold</Label>
          <Input
            id="drift-threshold"
            value={threshold}
            inputMode="decimal"
            placeholder="0.05"
            onChange={(e) => setThreshold(e.target.value)}
            className="h-9 w-32"
          />
        </div>
        <Button type="button" onClick={check} disabled={rebalance.isPending || !hasHoldings}>
          {rebalance.isPending ? "Checking…" : "Check drift"}
        </Button>
      </div>
      {!hasHoldings ? (
        <p className="text-xs text-muted-foreground">Add holdings before checking drift.</p>
      ) : null}

      {err?.kind === "no_targets" ? (
        <div className="rounded-md border border-primary/40 bg-primary/5 px-4 py-3 text-sm">
          <p className="font-medium text-foreground">No target weights set.</p>
          <p className="text-muted-foreground">
            Run an optimization and set targets first, then check drift.
          </p>
        </div>
      ) : err?.kind === "no_data" ? (
        <p className="text-sm text-muted-foreground">
          {err.detail ?? "No price data available to compute drift."}
        </p>
      ) : err ? (
        <p className="text-sm text-destructive">{err.detail ?? "Could not compute rebalancing."}</p>
      ) : null}

      {plan ? (
        <div className="space-y-3 rounded-lg border border-border bg-card p-4">
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Total drift</p>
              <p className="font-medium tabular-nums">{fmtPct(plan.total_drift)}</p>
            </div>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                plan.needs_rebalance
                  ? "bg-destructive/10 text-destructive"
                  : "bg-positive/10 text-positive",
              )}
            >
              {plan.needs_rebalance ? "Rebalance suggested" : "On plan"}
            </span>
          </div>

          {plan.trades.length === 0 ? (
            <p className="text-sm text-muted-foreground">On plan — no trades needed.</p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead className="text-right">Current</TableHead>
                    <TableHead className="text-right">Target</TableHead>
                    <TableHead className="text-right">Δ</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {plan.trades.map((t) => (
                    <TableRow key={t.stock_id}>
                      <TableCell className="font-medium">{t.symbol}</TableCell>
                      <TableCell
                        className={cn(
                          "uppercase",
                          t.direction === "buy" ? "text-positive" : "text-destructive",
                        )}
                      >
                        {t.direction}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtPct(t.current_weight)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtPct(t.target_weight)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtPct(t.delta_weight)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Button
                type="button"
                variant="outline"
                onClick={apply}
                disabled={applyTargets.isPending}
              >
                {applyTargets.isPending ? "Applying…" : "Apply targets"}
              </Button>
            </>
          )}
          <Disclaimer />
        </div>
      ) : null}
    </div>
  );
}

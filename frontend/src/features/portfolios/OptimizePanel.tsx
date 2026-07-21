"use client";

import { useEffect, useRef, useState } from "react";

import { Disclaimer } from "@/components/disclaimer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type OptimizeConstraints,
  OptimizeError,
  type OptimizeResponse,
  useOptimize,
} from "@/lib/api/queries";

type Objective = "max_sharpe" | "min_vol" | "target_return";

const OBJECTIVES: { value: Objective; label: string }[] = [
  { value: "max_sharpe", label: "Max Sharpe" },
  { value: "min_vol", label: "Min volatility" },
  { value: "target_return", label: "Target return" },
];

/** Format a Decimal-string as a percentage for display. */
function asPct(value: string | null | undefined): string {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : "—";
}

/** The optimize form + results. On success it lifts the weights up (for the chart) and shows
 * expected return/vol + per-constraint status; infeasible → binding constraint, Free → upgrade. */
export function OptimizePanel({
  portfolioId,
  canOptimize,
  hasHoldings,
  onOptimized,
}: {
  portfolioId: string;
  canOptimize: boolean;
  hasHoldings: boolean;
  onOptimized: (result: OptimizeResponse | null) => void;
}) {
  const [objective, setObjective] = useState<Objective>("max_sharpe");
  const [maxWeight, setMaxWeight] = useState("");
  const [targetReturn, setTargetReturn] = useState("");
  const [longOnly, setLongOnly] = useState(true);
  const optimize = useOptimize(portfolioId);

  const err = optimize.error instanceof OptimizeError ? optimize.error : null;

  // Inputs changed → the shown chart no longer matches them; clear it so a re-run is unambiguous
  // and the chart always reflects the latest optimization.
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    optimize.reset();
    onOptimized(null);
  }, [objective, maxWeight, targetReturn, longOnly]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = () => {
    const constraints: OptimizeConstraints = { long_only: longOnly };
    if (maxWeight.trim()) constraints.max_weight = maxWeight.trim();
    if (targetReturn.trim()) constraints.target_return = targetReturn.trim();
    optimize.mutate(
      {
        method: "mean_variance",
        objective,
        constraints,
        candidate_universe: "current_positions",
        risk_free_rate: "0",
      },
      { onSuccess: (result) => onOptimized(result ?? null) },
    );
  };

  if (!canOptimize) {
    return (
      <div className="rounded-md border border-primary/40 bg-primary/5 px-4 py-3 text-sm">
        <p className="font-medium text-foreground">Optimization is a paid feature.</p>
        <p className="text-muted-foreground">
          Upgrade your plan to optimize allocations.{" "}
          <a href="/pricing" className="text-primary hover:underline">
            See plans →
          </a>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="space-y-1">
          <Label htmlFor="objective">Objective</Label>
          <select
            id="objective"
            value={objective}
            onChange={(e) => setObjective(e.target.value as Objective)}
            className="h-9 w-full rounded-md border border-border bg-background px-2 text-sm"
          >
            {OBJECTIVES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="max-weight">Max weight</Label>
          <Input
            id="max-weight"
            value={maxWeight}
            inputMode="decimal"
            placeholder="e.g. 0.25"
            onChange={(e) => setMaxWeight(e.target.value)}
            className="h-9"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="target-return">Target return</Label>
          <Input
            id="target-return"
            value={targetReturn}
            inputMode="decimal"
            placeholder="e.g. 0.15"
            disabled={objective !== "target_return"}
            onChange={(e) => setTargetReturn(e.target.value)}
            className="h-9"
          />
        </div>
        <div className="flex items-end">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={longOnly}
              onChange={(e) => setLongOnly(e.target.checked)}
              className="size-4"
            />
            Long only
          </label>
        </div>
      </div>

      <Button type="button" onClick={run} disabled={optimize.isPending || !hasHoldings}>
        {optimize.isPending ? "Optimizing…" : "Run optimization"}
      </Button>
      {!hasHoldings ? (
        <p className="text-xs text-muted-foreground">Add holdings before optimizing.</p>
      ) : null}

      {err?.kind === "limit" ? (
        <div className="rounded-md border border-primary/40 bg-primary/5 px-4 py-3 text-sm">
          <p className="font-medium text-foreground">Optimization is a paid feature.</p>
          <p className="text-muted-foreground">
            Upgrade your plan to optimize.{" "}
            <a href="/pricing" className="text-primary hover:underline">
              See plans →
            </a>
          </p>
        </div>
      ) : err?.kind === "infeasible" ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm">
          <p className="font-medium text-foreground">No feasible allocation.</p>
          <p className="text-muted-foreground">{err.detail ?? "The constraints can’t all be met — try loosening them."}</p>
        </div>
      ) : err ? (
        <p className="text-sm text-destructive">
          {err.detail ?? "Could not optimize — check the constraints and try again."}
        </p>
      ) : null}

      {optimize.data ? (
        <div className="space-y-3 rounded-lg border border-border bg-card p-4">
          <div className="flex flex-wrap gap-6 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Expected return</p>
              <p className="font-medium tabular-nums">{asPct(optimize.data.expected_return)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Expected volatility</p>
              <p className="font-medium tabular-nums">{asPct(optimize.data.expected_volatility)}</p>
            </div>
          </div>
          <ul className="space-y-1 text-xs">
            {optimize.data.constraints.map((c) => (
              <li key={c.kind} className="flex items-center gap-2">
                <span className={c.satisfied ? "text-positive" : "text-destructive"}>
                  {c.satisfied ? "✓" : "✗"}
                </span>
                <span className="text-muted-foreground">{c.detail}</span>
              </li>
            ))}
          </ul>
          <Disclaimer />
        </div>
      ) : null}
    </div>
  );
}

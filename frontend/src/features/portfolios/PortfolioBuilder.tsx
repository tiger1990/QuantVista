"use client";

import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { type OptimizeResponse, usePositions } from "@/lib/api/queries";

import { OptimizePanel } from "./OptimizePanel";
import { PositionsEditor } from "./PositionsEditor";
import { WeightsChart } from "./WeightsChart";

/** The builder surface for one portfolio: holdings editor + optimize panel + weights chart.
 * Positions carry `symbol` (joined server-side), so names render directly. */
export function PortfolioBuilder({ portfolioId }: { portfolioId: string }) {
  const { user } = useAuth();
  const canOptimize = user?.entitlements?.optimization === true;

  const positions = usePositions(portfolioId);
  const items = positions.data ?? [];

  const [result, setResult] = useState<OptimizeResponse | null>(null);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Holdings</h2>
        {positions.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : positions.isError ? (
          <p className="text-sm text-destructive">Could not load holdings.</p>
        ) : (
          <PositionsEditor portfolioId={portfolioId} positions={items} />
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Optimize</h2>
        <OptimizePanel
          portfolioId={portfolioId}
          canOptimize={canOptimize}
          hasHoldings={items.length > 0}
          onOptimized={setResult}
        />
      </section>

      {result ? (
        <section className="space-y-3 lg:col-span-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Optimized vs current
          </h2>
          <WeightsChart positions={items} optimized={result.weights} />
        </section>
      ) : null}
    </div>
  );
}

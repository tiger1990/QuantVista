import type { Backtest } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

import { EquityCurveChart } from "./EquityCurveChart";
import { equityChartData, fmtPct, signOf } from "./lib";
import { MetricsTable } from "./MetricsTable";

const signClass = {
  pos: "text-[var(--color-positive)]",
  neg: "text-[var(--color-negative)]",
  zero: "",
};

/** The research tearsheet: masthead headline, the equity-vs-benchmark hero chart, the dense metrics
 * factsheet, and the reproducibility fingerprint + disclaimer footer. */
export function BacktestResults({ backtest }: { backtest: Backtest }) {
  const spec = backtest.spec as {
    rules?: { rank_by?: string; top_n?: number; rebalance?: string };
    start?: string;
    end?: string;
  };
  const m = (backtest.metrics ?? {}) as Record<string, unknown>;
  const rules = spec.rules ?? {};
  const chart = equityChartData(m);

  return (
    <article className="rounded-lg border border-border bg-card">
      {/* Masthead */}
      <header className="border-b border-border p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
              {rules.rank_by ?? "composite"} · top {rules.top_n ?? "—"} · {rules.rebalance ?? "—"}
            </p>
            <h2 className="mt-1 text-lg font-semibold tracking-tight">
              Backtest — {spec.start ?? "?"} → {spec.end ?? "?"}
            </h2>
          </div>
          <div className="text-right">
            <p
              className={cn(
                "font-mono text-3xl font-semibold tabular-nums",
                signClass[signOf(m.total_return)],
              )}
            >
              {fmtPct(m.total_return)}
            </p>
            <p className="text-xs text-muted-foreground">
              Nifty 200 {fmtPct(m.benchmark_return)} ·{" "}
              <span className={signClass[signOf(m.excess_return)]}>{fmtPct(m.excess_return)}</span>{" "}
              excess
            </p>
          </div>
        </div>
      </header>

      {/* Hero: equity curve */}
      <div className="p-5">
        <EquityCurveChart data={chart} />
      </div>

      {/* Dense metrics factsheet */}
      <div className="border-t border-border p-5">
        <MetricsTable metrics={m} />
      </div>

      {/* Footer: reproducibility + disclaimer */}
      <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-3">
        {/* Provenance (QV-069). A bare hex string means nothing on its own, so it says what it is
            and what it does NOT cover — the recipe, not the underlying market data. */}
        {typeof m.reproducibility_hash === "string" ? (
          <p
            className="font-mono text-[11px] text-muted-foreground"
            title={
              "Reproducibility fingerprint — SHA-256 of this run's settings plus the scoring model " +
              `(${String(m.model_version ?? "?")}) and weighting (${String(m.weights_version ?? "?")}) ` +
              "versions. Two runs sharing it used an identical recipe. It does not fingerprint the " +
              "underlying price or score data, which can change between runs."
            }
          >
            recipe {m.reproducibility_hash.slice(0, 12)}…
          </p>
        ) : null}
        {/* No Methodology link until the page exists (QV-070): it 404'd, which reads as a broken
            app. The disclaimer is deliberately self-contained so the tearsheet still ships whole. */}
        <p className="text-xs text-muted-foreground">
          Research tool, not investment advice — costs &amp; slippage are modelled assumptions and
          past performance does not indicate future results.
        </p>
      </footer>
    </article>
  );
}

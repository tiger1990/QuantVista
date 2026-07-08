import { Card, CardContent } from "@/components/ui/card";
import type { DecompositionResponse, FactorContribution } from "@/lib/api/queries";
import { groupByCategory, sumsToComposite } from "@/lib/decomposition";
import { formatScore } from "@/lib/score";
import { cn } from "@/lib/utils";

function num(value: number | null | undefined, digits = 2): string {
  return value == null ? "—" : value.toFixed(digits);
}

function FactorRow({ f, max }: { f: FactorContribution; max: number }) {
  const width = Math.max(2, (f.contribution / max) * 100);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="font-mono text-xs">{f.factor_key}</span>
        <span className="tabular-nums">{formatScore(f.contribution)}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${width}%` }} />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 text-[11px] text-muted-foreground">
        <span>raw {num(f.raw_value)}</span>
        <span>z {num(f.zscore)}</span>
        <span>
          pct {f.percentile_universe == null ? "—" : Math.round(f.percentile_universe)}
        </span>
        <span className="ml-auto">PIT {f.as_of}</span>
      </div>
    </div>
  );
}

/** The US-02 explainability view: contributions grouped by category that visibly sum to the composite. */
export function Decomposition({ data }: { data: DecompositionResponse }) {
  const groups = groupByCategory(data.factors);
  const max = Math.max(...data.factors.map((f) => f.contribution), 0.0001);
  const reconciled = sumsToComposite(data.sum_of_contributions, data.composite);

  return (
    <Card>
      <CardContent className="space-y-6">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Score decomposition</h2>
          <span className="text-xs text-muted-foreground">as of {data.as_of}</span>
        </div>

        {groups.length ? (
          groups.map((g) => (
            <div key={g.category} className="space-y-2">
              <div className="flex items-baseline justify-between text-xs uppercase tracking-wide text-muted-foreground">
                <span>{g.category}</span>
                <span className="tabular-nums">{formatScore(g.total)}</span>
              </div>
              <div className="space-y-2.5">
                {g.factors.map((f) => (
                  <FactorRow key={f.factor_key} f={f} max={max} />
                ))}
              </div>
            </div>
          ))
        ) : (
          <p className="py-4 text-sm text-muted-foreground">No factor contributions available.</p>
        )}

        <div
          className={cn(
            "flex items-center justify-between border-t border-border pt-3 text-sm font-medium",
            reconciled ? "text-foreground" : "text-destructive",
          )}
        >
          <span>Σ contributions {reconciled ? "=" : "≠"} composite</span>
          <span className="tabular-nums">
            {formatScore(data.sum_of_contributions)} / {formatScore(data.composite)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

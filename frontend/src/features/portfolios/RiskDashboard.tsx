"use client";

import { Disclaimer } from "@/components/disclaimer";
import { Card, CardContent } from "@/components/ui/card";
import { RiskError, useRisk } from "@/lib/api/queries";
import { fmtNum, fmtPct } from "@/lib/risk";

import { DrawdownChart } from "./DrawdownChart";
import { SectorExposureChart } from "./SectorExposureChart";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

/** Portfolio risk analytics: metric tiles + sector-exposure + drawdown-over-time. Read-only
 * research signal (not advice). No paid gate. */
export function RiskDashboard({ portfolioId }: { portfolioId: string }) {
  const risk = useRisk(portfolioId);

  if (risk.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading risk…</p>;
  }

  if (risk.isError) {
    const kind = risk.error instanceof RiskError ? risk.error.kind : "unknown";
    const message =
      kind === "no_data"
        ? "Add holdings with price history to assess risk."
        : kind === "not_found"
          ? "Portfolio not found."
          : "Could not load risk metrics.";
    return <p className="text-sm text-muted-foreground">{message}</p>;
  }

  const r = risk.data;
  if (!r) return null; // narrows the query data (isSuccess implies defined, but TS needs the guard)
  const cov = r.beta_coverage;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Metric label="Beta" value={fmtNum(r.beta)} />
          <Metric label="Volatility" value={fmtPct(r.volatility)} />
          <Metric label="Sharpe" value={fmtNum(r.sharpe)} />
          <Metric label="Sortino" value={fmtNum(r.sortino)} />
          <Metric label="Max drawdown" value={fmtPct(r.max_drawdown)} />
          <Metric label="Concentration (HHI)" value={fmtNum(r.hhi, 3)} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardContent className="space-y-2">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Sector exposure
            </h3>
            <SectorExposureChart exposure={r.sector_exposure} />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Drawdown over time
            </h3>
            <DrawdownChart series={r.drawdown_series} />
          </CardContent>
        </Card>
      </div>

      <p className="text-xs text-muted-foreground">
        As of {r.as_of_date} · beta covers {cov.covered}/{cov.total} holdings
      </p>
      <Disclaimer />
    </div>
  );
}

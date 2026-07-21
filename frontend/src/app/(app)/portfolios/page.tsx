"use client";

import { useAuth } from "@/components/auth-provider";
import { Disclaimer } from "@/components/disclaimer";
import { PortfolioList } from "@/features/portfolios/PortfolioList";
import { usePortfolios } from "@/lib/api/queries";

export default function PortfoliosPage() {
  const { user } = useAuth();
  const portfolios = usePortfolios();
  const items = portfolios.data ?? [];

  // entitlements.portfolios: number = cap, null/undefined = unlimited.
  const rawLimit = user?.entitlements?.portfolios;
  const limit = typeof rawLimit === "number" ? rawLimit : null;
  const atLimit = limit != null && items.length >= limit;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Portfolios</h1>
          <p className="text-sm text-muted-foreground">
            Build a portfolio, then optimize its allocation under your constraints.
          </p>
        </div>
        <p className="text-sm tabular-nums text-muted-foreground">
          {limit != null
            ? `${items.length} of ${limit} used`
            : `${items.length} ${items.length === 1 ? "portfolio" : "portfolios"}`}
        </p>
      </header>

      {portfolios.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : portfolios.isError ? (
        <p className="text-sm text-destructive">Could not load your portfolios.</p>
      ) : (
        <PortfolioList portfolios={items} atLimit={atLimit} />
      )}

      <Disclaimer />
    </div>
  );
}

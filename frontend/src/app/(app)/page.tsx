"use client";

import { useAuth } from "@/components/auth-provider";
import { MarketOverview, SectorHeatmap, TopRanked } from "@/components/dashboard";
import { Disclaimer } from "@/components/disclaimer";
import { useRankings, useStocks } from "@/lib/api/queries";

export default function OverviewPage() {
  const { user } = useAuth();
  const rankings = useRankings();
  const stocks = useStocks({});

  const items = rankings.data?.data ?? [];
  const asOf = (rankings.data?.meta as { as_of?: string | null } | undefined)?.as_of;
  const allStocks = stocks.data?.pages.flatMap((p) => p.data ?? []) ?? [];
  const firstName = user?.name?.split(" ")[0] ?? "there";

  return (
    <div className="space-y-6">
      <section className="space-y-1">
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          Equity research · India
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">Welcome back, {firstName}.</h1>
      </section>

      <MarketOverview items={items} asOf={asOf} />

      <div className="grid gap-4 lg:grid-cols-2">
        <TopRanked items={items} />
        <SectorHeatmap stocks={allStocks} />
      </div>

      <Disclaimer />
    </div>
  );
}

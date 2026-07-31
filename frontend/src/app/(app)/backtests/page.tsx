"use client";

import { Suspense } from "react";

import { useAuth } from "@/components/auth-provider";
import { BacktestList } from "@/features/backtests/BacktestList";
import { BacktestWorkbench } from "@/features/backtests/BacktestWorkbench";
import { tierFrom } from "@/features/backtests/lib";
import { useSelectedRun } from "@/features/backtests/useSelectedRun";
import { useBacktests } from "@/lib/api/queries";

export default function BacktestsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Backtests</h1>
        <p className="text-sm text-muted-foreground">
          Simulate a factor strategy over history — survivorship-free, point-in-time, cost-aware.
        </p>
      </header>
      {/* `useSelectedRun` reads search params — Suspense keeps the route statically prerenderable. */}
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <BacktestsWorkspace />
      </Suspense>
    </div>
  );
}

function BacktestsWorkspace() {
  const { user } = useAuth();
  const tier = tierFrom(user?.entitlements);
  const [selectedId, select] = useSelectedRun();
  const list = useBacktests();
  const items = list.data ?? [];

  return (
    <div className="space-y-6">
      <BacktestWorkbench tier={tier} activeId={selectedId} onSelect={select} />

      <section className="space-y-2">
        <h2 className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
          History
        </h2>
        {list.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : list.isError ? (
          <p className="text-sm text-destructive">Could not load your backtests.</p>
        ) : (
          <BacktestList items={items} selectedId={selectedId} onSelect={select} />
        )}
      </section>
    </div>
  );
}

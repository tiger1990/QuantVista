"use client";

import { useAuth } from "@/components/auth-provider";
import { Disclaimer } from "@/components/disclaimer";
import { AlertForm } from "@/features/alerts/AlertForm";
import { AlertList } from "@/features/alerts/AlertList";
import { useAlerts } from "@/lib/api/queries";

export default function AlertsPage() {
  const { user } = useAuth();
  const alerts = useAlerts();
  const rules = alerts.data ?? [];

  // entitlements.alerts: number = cap, null/undefined = unlimited.
  const rawLimit = user?.entitlements?.alerts;
  const limit = typeof rawLimit === "number" ? rawLimit : null;
  const atLimit = limit != null && rules.length >= limit;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Alerts</h1>
          <p className="text-sm text-muted-foreground">
            Get notified when a stock crosses a threshold you care about.
          </p>
        </div>
        <p className="text-sm tabular-nums text-muted-foreground">
          {rules.length} of {limit ?? "∞"} used
        </p>
      </header>

      <AlertForm atLimit={atLimit} />

      {alerts.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : alerts.isError ? (
        <p className="text-sm text-destructive">Could not load your alerts.</p>
      ) : (
        <AlertList rules={rules} />
      )}

      <Disclaimer />
    </div>
  );
}

"use client";

import { Bell, Mail, Trash2 } from "lucide-react";

import { type AlertRule, useDeleteAlert } from "@/lib/api/queries";

const OP_LABEL: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥", eq: "=" };

function conditionText(c: AlertRule["condition"]): string {
  const metric = String(c.metric ?? "").replace(/_/g, " ");
  return `${metric} ${OP_LABEL[String(c.op)] ?? c.op} ${c.value}`;
}

/** The user's alert rules with a delete action. */
export function AlertList({ rules }: { rules: AlertRule[] }) {
  const del = useDeleteAlert();
  if (rules.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No alerts yet.</p>;
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-card">
      {rules.map((r) => (
        <li key={r.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
          <div className="flex min-w-0 items-center gap-2">
            <span className="font-medium">{r.target_symbol ?? "—"}</span>
            <span className="truncate text-muted-foreground">{conditionText(r.condition)}</span>
          </div>
          <div className="flex shrink-0 items-center gap-3 text-muted-foreground">
            <span className="flex items-center gap-1 text-xs" title={`Channel: ${r.channel}`}>
              {r.channel === "email" ? <Mail className="size-3.5" /> : <Bell className="size-3.5" />}
              {r.channel === "email" ? "Email" : "In-app"}
            </span>
            <button
              type="button"
              onClick={() => del.mutate(r.id)}
              disabled={del.isPending}
              aria-label={`Delete alert on ${r.target_symbol ?? "stock"}`}
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="size-4" />
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

import { cn } from "@/lib/utils";

import { metricGroups, type Sign } from "./lib";

const signClass: Record<Sign, string> = {
  pos: "text-[var(--color-positive)]",
  neg: "text-[var(--color-negative)]",
  zero: "text-foreground",
};

/** Dense analyst factsheet: the QV-068 suite in grouped, hairline-separated rows with tabular
 * figures — not one metric per card. Two columns of groups on wide screens. */
export function MetricsTable({ metrics }: { metrics: Record<string, unknown> }) {
  const groups = metricGroups(metrics);
  return (
    <div className="grid grid-cols-1 gap-x-10 gap-y-6 sm:grid-cols-2">
      {groups.map((group) => (
        <section key={group.title} aria-label={group.title}>
          <h3 className="mb-1 text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
            {group.title}
          </h3>
          <dl className="divide-y divide-border">
            {group.rows.map((row) => (
              <div key={row.label} className="flex items-baseline justify-between py-1.5 text-sm">
                <dt className="text-muted-foreground">{row.label}</dt>
                <dd className={cn("font-mono tabular-nums", row.sign ? signClass[row.sign] : "")}>
                  {row.value}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}

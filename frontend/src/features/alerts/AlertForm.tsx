"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CreateAlertError, useCreateAlert, useStocks } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const METRICS: { value: string; label: string }[] = [
  { value: "composite_score", label: "Composite score" },
  { value: "fundamental_score", label: "Fundamental score" },
  { value: "momentum_score", label: "Momentum score" },
  { value: "quality_score", label: "Quality score" },
  { value: "sentiment_score", label: "Sentiment score" },
  { value: "risk_score", label: "Risk score" },
  { value: "coverage", label: "Coverage" },
  { value: "pe", label: "P/E" },
  { value: "pb", label: "P/B" },
  { value: "roe", label: "ROE" },
  { value: "roce", label: "ROCE" },
  { value: "debt_equity", label: "Debt / Equity" },
];
type Op = "lt" | "lte" | "gt" | "gte" | "eq";
const OPS: { value: Op; label: string }[] = [
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "eq", label: "=" },
];

const selectClass =
  "h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

/** Create an alert rule: pick a stock, a metric/op/threshold, and a delivery channel. */
export function AlertForm({ atLimit }: { atLimit: boolean }) {
  const create = useCreateAlert();
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<{ id: string; symbol: string } | null>(null);
  const [metric, setMetric] = useState("composite_score");
  const [op, setOp] = useState<Op>("lt");
  const [value, setValue] = useState("50");
  const [channel, setChannel] = useState<"in_app" | "email">("in_app");
  const [err, setErr] = useState<string | null>(null);

  const results = useStocks({ q: query.trim() || undefined });
  const matches = target ? [] : (results.data?.pages.flatMap((p) => p.data ?? []) ?? []).slice(0, 6);

  const submit = () => {
    setErr(null);
    if (!target) return setErr("Pick a stock first.");
    const num = Number(value);
    if (Number.isNaN(num)) return setErr("Threshold must be a number.");
    create.mutate(
      { scope: "stock", target_id: target.id, condition: { metric, op, value: num }, channel },
      {
        onSuccess: () => {
          setTarget(null);
          setQuery("");
          setValue("50");
        },
        onError: (e) => {
          if (e instanceof CreateAlertError && e.kind === "limit")
            setErr("You've reached your plan's alert limit. Upgrade for more.");
          else if (e instanceof CreateAlertError && e.kind === "invalid")
            setErr("That condition isn't valid.");
          else setErr("Could not create the alert.");
        },
      },
    );
  };

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">New alert</h2>

      {target ? (
        <div className="flex items-center gap-2 text-sm">
          <span className="rounded-md bg-muted px-2 py-1 font-medium">{target.symbol}</span>
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setTarget(null)}
          >
            change
          </button>
        </div>
      ) : (
        <div className="relative">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search a stock (symbol or company)…"
            aria-label="Stock"
          />
          {query.trim() && matches.length > 0 ? (
            <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-md border border-border bg-popover shadow-md">
              {matches.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-muted"
                    onClick={() => setTarget({ id: s.id, symbol: s.symbol })}
                  >
                    <span className="font-medium">{s.symbol}</span>
                    <span className="truncate pl-3 text-xs text-muted-foreground">
                      {s.company_name}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <select
          className={selectClass}
          value={metric}
          onChange={(e) => setMetric(e.target.value)}
          aria-label="Metric"
        >
          {METRICS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        <select
          className={selectClass}
          value={op}
          onChange={(e) => setOp(e.target.value as Op)}
          aria-label="Operator"
        >
          {OPS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <Input
          type="number"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="w-24"
          aria-label="Threshold"
        />
        <select
          className={selectClass}
          value={channel}
          onChange={(e) => setChannel(e.target.value as "in_app" | "email")}
          aria-label="Channel"
        >
          <option value="in_app">In-app</option>
          <option value="email">Email</option>
        </select>
        <Button
          size="sm"
          onClick={submit}
          disabled={atLimit || create.isPending}
          className={cn(atLimit && "opacity-50")}
        >
          {create.isPending ? "Creating…" : "Create alert"}
        </Button>
      </div>

      {atLimit ? (
        <p className="text-xs text-muted-foreground">
          You&apos;re at your plan&apos;s alert limit — delete one or upgrade to add more.
        </p>
      ) : null}
      {err ? <p className="text-xs text-destructive">{err}</p> : null}
    </div>
  );
}

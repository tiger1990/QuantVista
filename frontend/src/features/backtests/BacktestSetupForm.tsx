"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { type BacktestSpec, SubmitBacktestError, useSubmitBacktest } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

import { PRESETS, presetRange, rangeDays, type Tier } from "./lib";
import { SymbolPicker } from "./SymbolPicker";

const selectClass =
  "h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-sm " +
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

type RankBy = "composite" | "fundamental" | "momentum" | "quality" | "sentiment" | "risk";
type Rebalance = "weekly" | "monthly" | "quarterly";
type StrategyType = "factor_strategy" | "custom_basket";
/** Mirrors `MAX_BASKET_SYMBOLS` in the backend spec — the server is still the backstop. */
export const MAX_BASKET_SYMBOLS = 50;
const RANK_BY: RankBy[] = ["composite", "fundamental", "momentum", "quality", "sentiment", "risk"];
const REBALANCE: Rebalance[] = ["weekly", "monthly", "quarterly"];

/** Submit failures, told apart. Only a real 422 blames the inputs — an unreachable/erroring API
 * (404, 5xx, network) must NOT say "check the inputs" or it sends you debugging a valid spec. */
export function submitErrorMessage(e: unknown): string {
  const kind = e instanceof SubmitBacktestError ? e.kind : "unknown";
  if (kind === "entitlement")
    return "This range needs the Quant plan. Upgrade to run custom backtests.";
  if (kind === "invalid")
    return "That backtest spec was rejected — check the inputs and try again.";
  return "Couldn't reach the backtest service. Your inputs look fine — please retry shortly.";
}

/** The "new backtest" panel: strategy rules + range + costs, tier-gated. Free → upsell; Pro →
 * ≤1y presets; Quant → custom range. The server 403 is the backstop, surfaced as an upgrade note. */
export function BacktestSetupForm({
  tier,
  onQueued,
}: {
  tier: Tier;
  onQueued: (id: string) => void;
}) {
  const submit = useSubmitBacktest();
  const [mode, setMode] = useState<StrategyType>("factor_strategy");
  const [symbols, setSymbols] = useState<string[]>([]);
  const [rankBy, setRankBy] = useState<RankBy>("composite");
  const [topN, setTopN] = useState(20);
  const [rebalance, setRebalance] = useState<Rebalance>("monthly");
  const [costsBps, setCostsBps] = useState(15);
  const [preset, setPreset] = useState(12); // months (Free/Pro)
  // Default the custom range to a trailing year, NOT a hardcoded past one: a fixed 2020 default
  // sits outside the ingested price history, so the out-of-the-box run returns an empty tearsheet.
  const [start, setStart] = useState(() => presetRange(12).start);
  const [end, setEnd] = useState(() => presetRange(12).end);
  const [err, setErr] = useState<string | null>(null);

  if (tier === "free") {
    return (
      <div className="rounded-lg border border-border bg-card p-6">
        <h2 className="text-sm font-medium">Backtesting is a paid feature</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Upgrade to Pro to backtest factor strategies over the last year, or Quant for custom
          ranges and full metrics.
        </p>
        <Button asChild className="mt-4" size="sm">
          <Link href="/settings/billing">Upgrade</Link>
        </Button>
      </div>
    );
  }

  const isQuant = tier === "quant";

  const run = (): void => {
    setErr(null);
    const range = isQuant ? { start, end } : presetRange(preset);
    if (Date.parse(range.start) >= Date.parse(range.end)) {
      setErr("Start date must be before the end date.");
      return;
    }
    if (!isQuant && rangeDays(range.start, range.end) > 366) {
      setErr("Pro backtests are limited to 1 year — upgrade to Quant for custom ranges.");
      return;
    }
    const isBasket = mode === "custom_basket";
    if (isBasket && symbols.length === 0) {
      setErr("Add at least one symbol to backtest a custom basket.");
      return;
    }
    const spec: BacktestSpec = {
      type: mode,
      universe: "NIFTY200",
      // rank_by/top_n are inert for a basket but always sent: the server fills its defaults into
      // the stored spec regardless, so omitting them would change nothing except the wire shape.
      rules: { rank_by: rankBy, top_n: topN, rebalance },
      ...(isBasket ? { symbols } : {}),
      start: range.start,
      end: range.end,
      costs_bps: costsBps,
      benchmark: "NIFTY200_TRI",
    };
    submit.mutate(spec, {
      onSuccess: (row) => onQueued(row.id),
      onError: (e) => setErr(submitErrorMessage(e)),
    });
  };

  return (
    <form
      className="rounded-lg border border-border bg-card p-5"
      onSubmit={(e) => {
        e.preventDefault();
        run();
      }}
    >
      <div
        role="radiogroup"
        aria-label="Strategy"
        className="mb-4 flex gap-1.5 border-b border-border pb-4"
      >
        {(
          [
            ["factor_strategy", "Factor strategy"],
            ["custom_basket", "Custom basket"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={mode === value}
            onClick={() => setMode(value)}
            className={cn(
              "rounded-sm border px-3 py-1 text-sm transition-colors",
              mode === value
                ? "border-primary bg-primary/10 font-medium text-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
        <span className="ml-2 self-center text-xs text-muted-foreground">
          {mode === "custom_basket"
            ? "Your picks, equal-weighted, vs the index."
            : "Rank the index and hold the top N."}
        </span>
      </div>

      {mode === "custom_basket" ? (
        <div className="mb-4">
          <span className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
            Basket
          </span>
          <div className="mt-1">
            <SymbolPicker selected={symbols} onChange={setSymbols} max={MAX_BASKET_SYMBOLS} />
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {mode === "factor_strategy" ? (
          <>
            <Field label="Rank by">
              <select
                className={selectClass}
                value={rankBy}
                onChange={(e) => setRankBy(e.target.value as RankBy)}
              >
                {RANK_BY.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Top N">
              <Input
                type="number"
                min={1}
                max={200}
                value={topN}
                onChange={(e) => setTopN(Number(e.target.value))}
              />
            </Field>
          </>
        ) : null}
        <Field label="Rebalance">
          <select
            className={selectClass}
            value={rebalance}
            onChange={(e) => setRebalance(e.target.value as Rebalance)}
          >
            {REBALANCE.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Costs (bps)">
          <Input
            type="number"
            min={0}
            max={500}
            value={costsBps}
            onChange={(e) => setCostsBps(Number(e.target.value))}
          />
        </Field>
      </div>

      <div className="mt-4">
        {isQuant ? (
          <div className="grid grid-cols-2 gap-4 sm:max-w-md">
            <Field label="Start">
              <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            </Field>
            <Field label="End">
              <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
            </Field>
          </div>
        ) : (
          <div>
            <span className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
              Range
            </span>
            <div className="mt-1 flex gap-1.5">
              {PRESETS.map((p) => (
                <button
                  key={p.months}
                  type="button"
                  onClick={() => setPreset(p.months)}
                  className={cn(
                    "rounded-sm border px-3 py-1 text-sm transition-colors",
                    preset === p.months
                      ? "border-primary bg-primary/10 font-medium text-foreground"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  {p.label}
                </button>
              ))}
              <span className="ml-2 self-center text-xs text-muted-foreground">
                Custom ranges need Quant.
              </span>
            </div>
          </div>
        )}
      </div>

      {err ? <p className="mt-3 text-sm text-destructive">{err}</p> : null}

      <div className="mt-4 flex items-center gap-3">
        <Button type="submit" size="sm" disabled={submit.isPending}>
          {submit.isPending ? "Submitting…" : "Run backtest"}
        </Button>
        <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          {isQuant ? "Quant · custom" : "Pro · ≤ 1 year"}
        </span>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] uppercase tracking-widest text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

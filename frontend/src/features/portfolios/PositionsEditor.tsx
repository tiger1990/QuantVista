"use client";

import { Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type Position,
  useDeletePosition,
  useStocks,
  useUpsertPosition,
} from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const EPSILON = 0.0001;

/** Trim a Decimal-string weight for display: "0.200000" → "0.2"; zero/unset → "". */
function fmtWeight(v: string | null | undefined): string {
  const n = Number(v ?? 0);
  return Number.isFinite(n) && n > 0 ? String(n) : "";
}

/** A holding's target-weight input. Auto-saves (debounced) as you type AND on blur, so a quick
 * page refresh doesn't lose the edit.
 *
 * Depends only on the STABLE `mutate` (not the whole mutation object) and compares against the
 * persisted value via a ref — so a field's debounce timer resets only when its OWN value changes,
 * never on the re-render churn from a sibling field's save. */
function WeightInput({
  portfolioId,
  position,
}: {
  portfolioId: string;
  position: Position;
}) {
  const { mutate } = useUpsertPosition(portfolioId); // stable reference
  const stockId = position.stock_id;
  const persisted = fmtWeight(position.target_weight);
  const [value, setValue] = useState(persisted);

  const persistedRef = useRef(persisted);
  useEffect(() => {
    persistedRef.current = persisted; // track the latest server value without triggering saves
  }, [persisted]);

  const save = (next: string) => {
    if (next.trim() === persistedRef.current) return; // no change vs. persisted
    mutate({ stockId, body: { target_weight: next.trim() || "0" } });
  };

  useEffect(() => {
    if (value.trim() === persistedRef.current) return;
    const t = setTimeout(() => mutate({ stockId, body: { target_weight: value.trim() || "0" } }), 500);
    return () => clearTimeout(t);
  }, [value, mutate, stockId]);

  return (
    <Input
      aria-label="Target weight"
      value={value}
      inputMode="decimal"
      placeholder="0.00"
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => save(value)}
      className="h-8 w-20 text-right tabular-nums"
    />
  );
}

/** Add/remove holdings and set target weights. Positions carry `symbol` (joined server-side). */
export function PositionsEditor({
  portfolioId,
  positions,
}: {
  portfolioId: string;
  positions: Position[];
}) {
  const [q, setQ] = useState("");
  const results = useStocks({ q: q.trim() || null });
  const upsert = useUpsertPosition(portfolioId);
  const del = useDeletePosition(portfolioId);

  const held = new Set(positions.map((p) => p.stock_id));
  const totalWeight = positions.reduce((sum, p) => sum + Number(p.target_weight ?? 0), 0);
  const matches = (results.data?.pages.flatMap((page) => page.data ?? []) ?? [])
    .filter((s) => !held.has(s.id))
    .slice(0, 6);

  const add = (stockId: string) => {
    upsert.mutate({ stockId, body: { target_weight: "0" } }, { onSuccess: () => setQ("") });
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <Input
          aria-label="Search stocks to add"
          value={q}
          placeholder="Search a stock to add…"
          onChange={(e) => setQ(e.target.value)}
          className="h-9"
        />
        {q.trim() && matches.length > 0 ? (
          <ul className="divide-y divide-border rounded-md border border-border bg-popover">
            {matches.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm">
                <span className="min-w-0 truncate">
                  <span className="font-medium">{s.symbol}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{s.company_name}</span>
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={upsert.isPending}
                  aria-label={`Add ${s.symbol}`}
                  onClick={() => add(s.id)}
                >
                  <Plus className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {positions.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No holdings yet — search above to add stocks.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {positions.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
              <span className="min-w-0 truncate font-medium">{p.symbol}</span>
              <div className="flex shrink-0 items-center gap-3">
                <WeightInput portfolioId={portfolioId} position={p} />
                <button
                  type="button"
                  onClick={() => del.mutate(p.stock_id)}
                  disabled={del.isPending}
                  aria-label={`Remove ${p.symbol}`}
                  className="text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {positions.length > 0 ? (
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">
            Weights are optional — used only as your “current” baseline; the optimizer sets its own.
          </span>
          <span
            className={cn(
              "tabular-nums",
              totalWeight > 1 + EPSILON ? "text-destructive" : "text-muted-foreground",
            )}
          >
            Total: {(totalWeight * 100).toFixed(0)}% of 100%
          </span>
        </div>
      ) : null}
    </div>
  );
}

"use client";

import { Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { DeleteButton } from "@/components/delete-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { type Position, useDeletePosition, useStocks, useUpsertPosition } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const EPSILON = 0.0001;

type EditableField = "shares" | "target_weight";

/** Trim a Decimal-string for display: "0.200000" → "0.2"; zero/unset → "". */
function fmtNum(v: string | null | undefined): string {
  const n = Number(v ?? 0);
  return Number.isFinite(n) && n > 0 ? String(n) : "";
}

/** One editable numeric field of a holding (`shares` or `target_weight`). Auto-saves (debounced)
 * as you type AND on blur, so a quick page refresh doesn't lose the edit. The partial upsert
 * preserves the OTHER fields server-side (COALESCE), so editing shares never clears the target.
 *
 * Depends only on the STABLE `mutate` (not the whole mutation object) and compares against the
 * persisted value via a ref — so a field's debounce timer resets only when its OWN value changes,
 * never on the re-render churn from a sibling field's save. */
function PositionField({
  portfolioId,
  position,
  field,
  label,
  placeholder,
}: {
  portfolioId: string;
  position: Position;
  field: EditableField;
  label: string;
  placeholder: string;
}) {
  const { mutate } = useUpsertPosition(portfolioId); // stable reference
  const stockId = position.stock_id;
  const persisted = fmtNum(position[field]);
  const [value, setValue] = useState(persisted);

  const persistedRef = useRef(persisted);
  useEffect(() => {
    persistedRef.current = persisted; // track the latest server value without triggering saves
  }, [persisted]);

  const save = (next: string) => {
    if (next.trim() === persistedRef.current) return; // no change vs. persisted
    mutate({ stockId, body: { [field]: next.trim() || "0" } });
  };

  useEffect(() => {
    if (value.trim() === persistedRef.current) return;
    const t = setTimeout(() => mutate({ stockId, body: { [field]: value.trim() || "0" } }), 500);
    return () => clearTimeout(t);
  }, [value, mutate, stockId, field]);

  return (
    <Input
      aria-label={label}
      value={value}
      inputMode="decimal"
      placeholder={placeholder}
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
              <li
                key={s.id}
                className="flex items-center justify-between gap-2 px-3 py-1.5 text-sm"
              >
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
        <div className="rounded-lg border border-border bg-card">
          <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-1.5 text-xs text-muted-foreground">
            <span>Holding</span>
            <div className="flex shrink-0 items-center gap-3">
              <span className="w-20 text-right">Shares</span>
              <span className="w-20 text-right">Target wt</span>
              <span className="w-4" />
            </div>
          </div>
          <ul className="divide-y divide-border">
            {positions.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                <span className="min-w-0 truncate font-medium">{p.symbol}</span>
                <div className="flex shrink-0 items-center gap-3">
                  <PositionField
                    portfolioId={portfolioId}
                    position={p}
                    field="shares"
                    label={`Shares held of ${p.symbol}`}
                    placeholder="0"
                  />
                  <PositionField
                    portfolioId={portfolioId}
                    position={p}
                    field="target_weight"
                    label={`Target weight of ${p.symbol}`}
                    placeholder="0.00"
                  />
                  <DeleteButton
                    label={`Remove ${p.symbol}`}
                    pending={del.isPending}
                    onConfirm={() => del.mutate(p.stock_id)}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {positions.length > 0 ? (
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">
            Enter <strong>shares</strong> you actually hold so drift compares real vs. target;
            <strong> target wt</strong> is your desired allocation.
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

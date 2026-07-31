"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";
import { useStocks } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

/** Search-and-pick the names a custom basket holds. Server-side search (whole universe, not just a
 * loaded page); picks are shown as removable chips so the basket is always legible at a glance. */
export function SymbolPicker({
  selected,
  onChange,
  max,
  disabled,
}: {
  selected: string[];
  onChange: (symbols: string[]) => void;
  max: number;
  disabled?: boolean;
}) {
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");

  // Debounce the search so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setQ(term.trim()), 250);
    return () => clearTimeout(t);
  }, [term]);

  const results = useStocks({ q: q || null });
  const matches = (results.data?.pages?.[0]?.data ?? []).slice(0, 8);
  const isFull = selected.length >= max;

  const add = (symbol: string): void => {
    if (isFull || selected.includes(symbol)) return;
    onChange([...selected, symbol]);
    setTerm("");
    setQ("");
  };

  return (
    <div className="space-y-2">
      {selected.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5">
          {selected.map((s) => (
            <li key={s}>
              <span className="inline-flex items-center gap-1 rounded-sm border border-border bg-muted/40 py-0.5 pl-2 pr-1 font-mono text-xs">
                {s}
                <button
                  type="button"
                  aria-label={`Remove ${s}`}
                  disabled={disabled}
                  onClick={() => onChange(selected.filter((x) => x !== s))}
                  className="rounded-sm text-muted-foreground transition-colors hover:text-destructive focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <X className="size-3" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <Input
        type="search"
        value={term}
        disabled={disabled || isFull}
        onChange={(e) => setTerm(e.target.value)}
        placeholder={isFull ? `Basket is full (${max})` : "Search a symbol or company…"}
        aria-label="Search symbols to add"
      />

      {q && !isFull ? (
        <div className="rounded-md border border-border">
          {results.isLoading ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">Searching…</p>
          ) : matches.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">No matches for “{q}”.</p>
          ) : (
            <ul className="divide-y divide-border">
              {matches.map((m) => {
                const picked = selected.includes(m.symbol);
                return (
                  <li key={m.id}>
                    <button
                      type="button"
                      disabled={picked}
                      onClick={() => add(m.symbol)}
                      className={cn(
                        "flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-sm",
                        "transition-colors hover:bg-muted/50 focus-visible:outline-none",
                        "focus-visible:ring-1 focus-visible:ring-ring",
                        picked && "opacity-50",
                      )}
                    >
                      <span className="font-mono text-xs">{m.symbol}</span>
                      <span className="truncate text-xs text-muted-foreground">
                        {m.company_name}
                      </span>
                      {picked ? (
                        <span className="ml-auto text-[11px] text-muted-foreground">added</span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}

      <p className="text-[11px] text-muted-foreground">
        {selected.length}/{max} selected · held equal-weighted and rebalanced on your cadence
      </p>
    </div>
  );
}

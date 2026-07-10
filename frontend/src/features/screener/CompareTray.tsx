"use client";

import { X } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { COMPARE_MAX } from "@/lib/screener";

interface CompareTrayProps {
  symbols: string[];
  onRemove: (symbol: string) => void;
  onClear: () => void;
}

/** Sticky tray of picked symbols; "Compare" deep-links to /compare?symbols=… (shareable). */
export function CompareTray({ symbols, onRemove, onClear }: CompareTrayProps) {
  if (symbols.length === 0) return null;

  return (
    <div className="sticky bottom-4 z-30 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-background/95 p-3 shadow-lg backdrop-blur">
      <span className="text-xs text-muted-foreground">
        Compare ({symbols.length}/{COMPARE_MAX}):
      </span>
      {symbols.map((symbol) => (
        <span
          key={symbol}
          className="inline-flex items-center gap-1 rounded-sm bg-muted px-2 py-1 text-xs"
        >
          {symbol}
          <button type="button" aria-label={`Remove ${symbol}`} onClick={() => onRemove(symbol)}>
            <X className="size-3" />
          </button>
        </span>
      ))}
      <div className="ml-auto flex items-center gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onClear}>
          Clear
        </Button>
        {symbols.length < 2 ? (
          <Button type="button" size="sm" disabled>
            Compare →
          </Button>
        ) : (
          <Button asChild size="sm">
            <Link href={`/compare?symbols=${symbols.join(",")}`}>Compare →</Link>
          </Button>
        )}
      </div>
    </div>
  );
}

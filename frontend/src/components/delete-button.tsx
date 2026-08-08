"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Delete control with an inline confirm — the one implementation every surface uses.
 *
 * Deletion here is irreversible and the affected records are not cheap to recreate: a portfolio's
 * holdings, a saved screen's criteria, an alert rule. The confirm is inline rather than a modal so
 * it stays in the row it belongs to and does not interrupt the page.
 *
 * Shared deliberately: the app previously had five near-identical trash buttons, only one of which
 * asked before destroying anything.
 */
export function DeleteButton({
  onConfirm,
  label,
  pending = false,
  className,
}: {
  /** Runs only after the user confirms. */
  onConfirm: () => void;
  /** Accessible name for the trigger, e.g. `Delete portfolio Growth`. */
  label: string;
  pending?: boolean;
  className?: string;
}) {
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <span className={cn("flex shrink-0 items-center gap-1.5 text-xs", className)}>
        <span className="text-muted-foreground">Delete?</span>
        <button
          type="button"
          onClick={() => {
            setConfirming(false);
            onConfirm();
          }}
          className="rounded-sm px-1.5 py-0.5 font-medium text-destructive transition-colors hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          Delete
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="rounded-sm px-1.5 py-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          Cancel
        </button>
      </span>
    );
  }

  return (
    <button
      type="button"
      aria-label={label}
      disabled={pending}
      onClick={() => setConfirming(true)}
      className={cn(
        "shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors",
        "hover:text-destructive focus-visible:outline-none focus-visible:ring-1",
        "focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
    >
      <Trash2 className="size-4" />
    </button>
  );
}

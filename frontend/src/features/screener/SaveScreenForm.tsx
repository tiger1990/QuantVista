"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SaveScreenError, useSaveScreen } from "@/lib/api/queries";
import type { ScreenCriteria } from "@/lib/screener";

interface SaveScreenFormProps {
  criteria: ScreenCriteria;
}

const MESSAGES: Record<string, string> = {
  conflict: "A screen with that name already exists.",
  invalid: "This screen can’t be saved — check the filters.",
  unknown: "Could not save the screen. Please try again.",
};

/**
 * Inline "save this screen" form. On the Free-tier cap the API returns 403 `entitlement_exceeded`;
 * we surface an upgrade CTA (US-06) rather than a bare error. 409 → name-taken, 422 → invalid.
 */
export function SaveScreenForm({ criteria }: SaveScreenFormProps) {
  const [name, setName] = useState("");
  const save = useSaveScreen();
  const kind = save.error instanceof SaveScreenError ? save.error.kind : null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    save.mutate(
      { name: trimmed, criteria },
      { onSuccess: () => setName("") },
    );
  };

  return (
    <div className="space-y-2">
      <form onSubmit={submit} className="flex items-center gap-2">
        <Input
          aria-label="Screen name"
          value={name}
          placeholder="Name this screen…"
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          className="h-9 w-56"
        />
        <Button type="submit" size="sm" disabled={save.isPending || !name.trim()}>
          {save.isPending ? "Saving…" : "Save screen"}
        </Button>
      </form>

      {save.isSuccess ? <p className="text-xs text-positive">Saved.</p> : null}

      {kind === "limit" ? (
        <div className="rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-xs">
          <p className="font-medium text-foreground">You’ve hit your saved-screen limit.</p>
          <p className="text-muted-foreground">
            Upgrade your plan to save more screens.{" "}
            <a href="/pricing" className="text-primary hover:underline">
              See plans →
            </a>
          </p>
        </div>
      ) : kind ? (
        <p className="text-xs text-destructive">{MESSAGES[kind] ?? MESSAGES.unknown}</p>
      ) : null}
    </div>
  );
}

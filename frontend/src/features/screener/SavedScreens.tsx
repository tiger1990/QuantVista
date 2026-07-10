"use client";

import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { type SavedScreen, useDeleteScreen, useSavedScreens } from "@/lib/api/queries";
import type { ScreenCriteria } from "@/lib/screener";

interface SavedScreensProps {
  onLoad: (criteria: ScreenCriteria) => void;
}

/** The tenant's saved screens: click to hydrate the builder, trash to delete (RLS-scoped). */
export function SavedScreens({ onLoad }: SavedScreensProps) {
  const { data, isLoading, isError } = useSavedScreens();
  const del = useDeleteScreen();

  if (isLoading) return <p className="text-xs text-muted-foreground">Loading saved screens…</p>;
  if (isError) return <p className="text-xs text-destructive">Could not load saved screens.</p>;

  const screens = data ?? [];
  if (screens.length === 0) {
    return <p className="text-xs text-muted-foreground">No saved screens yet.</p>;
  }

  return (
    <ul className="space-y-1">
      {screens.map((screen: SavedScreen) => (
        <li key={screen.id} className="flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => onLoad(screen.criteria as unknown as ScreenCriteria)}
            className="truncate text-left text-sm text-foreground hover:text-primary hover:underline"
          >
            {screen.name}
          </button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Delete ${screen.name}`}
            disabled={del.isPending}
            onClick={() => del.mutate(screen.id)}
          >
            <Trash2 className="size-4 text-muted-foreground" />
          </Button>
        </li>
      ))}
    </ul>
  );
}

"use client";

import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  CreatePortfolioError,
  type Portfolio,
  useCreatePortfolio,
  useDeletePortfolio,
} from "@/lib/api/queries";

/** Inline create form. On the Free-tier cap the API returns 403 → upgrade CTA (US-06). */
function CreatePortfolioForm({ atLimit }: { atLimit: boolean }) {
  const [name, setName] = useState("");
  const create = useCreatePortfolio();
  const overCap = atLimit || (create.error instanceof CreatePortfolioError && create.error.kind === "limit");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    create.mutate({ name: trimmed }, { onSuccess: () => setName("") });
  };

  return (
    <div className="space-y-2">
      <form onSubmit={submit} className="flex items-center gap-2">
        <Input
          aria-label="Portfolio name"
          value={name}
          placeholder="Name a new portfolio…"
          maxLength={120}
          disabled={atLimit}
          onChange={(e) => setName(e.target.value)}
          className="h-9 w-64"
        />
        <Button type="submit" size="sm" disabled={create.isPending || !name.trim() || atLimit}>
          {create.isPending ? "Creating…" : "New portfolio"}
        </Button>
      </form>

      {overCap ? (
        <div className="rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-xs">
          <p className="font-medium text-foreground">You’ve reached your portfolio limit.</p>
          <p className="text-muted-foreground">
            Upgrade your plan to build more portfolios.{" "}
            <a href="/pricing" className="text-primary hover:underline">
              See plans →
            </a>
          </p>
        </div>
      ) : create.isError ? (
        <p className="text-xs text-destructive">Could not create the portfolio. Please try again.</p>
      ) : null}
    </div>
  );
}

/** The tenant's portfolios: create + list + delete, each linking to its builder. */
export function PortfolioList({ portfolios, atLimit }: { portfolios: Portfolio[]; atLimit: boolean }) {
  const del = useDeletePortfolio();

  return (
    <div className="space-y-4">
      <CreatePortfolioForm atLimit={atLimit} />

      {portfolios.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          No portfolios yet — create one to start building.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {portfolios.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
              <Link
                href={`/portfolios/${p.id}`}
                className="min-w-0 flex-1 font-medium hover:text-primary hover:underline"
              >
                {p.name}
                <span className="ml-2 text-xs font-normal text-muted-foreground">{p.benchmark}</span>
              </Link>
              <button
                type="button"
                onClick={() => del.mutate(p.id)}
                disabled={del.isPending}
                aria-label={`Delete portfolio ${p.name}`}
                className="shrink-0 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

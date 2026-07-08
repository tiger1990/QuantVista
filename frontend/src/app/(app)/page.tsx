"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { Card, CardContent, CardDescription, CardTitle } from "@/components/ui/card";

const ENTRIES = [
  {
    href: "/rankings",
    title: "Rankings",
    description: "The NIFTY 200 universe ranked by composite score.",
  },
  {
    href: "/stocks",
    title: "Stocks",
    description: "Browse the universe — filter, sort, inspect a stock's snapshot.",
  },
];

export default function OverviewPage() {
  const { user } = useAuth();
  const firstName = user?.name?.split(" ")[0] ?? "there";

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          Equity research · India
        </p>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          Welcome back, {firstName}.
        </h1>
        <p className="max-w-xl text-muted-foreground">
          Explainable, point-in-time equity scores for the NIFTY 200. The dashboard and live rankings
          land next — the engine and API are ready.
        </p>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        {ENTRIES.map((entry) => (
          <Link key={entry.href} href={entry.href} className="group">
            <Card className="h-full transition-colors group-hover:border-primary/50">
              <CardContent className="flex items-start justify-between gap-4">
                <div className="space-y-1">
                  <CardTitle className="text-lg">{entry.title}</CardTitle>
                  <CardDescription>{entry.description}</CardDescription>
                </div>
                <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
              </CardContent>
            </Card>
          </Link>
        ))}
      </section>

      <p className="text-xs text-muted-foreground">Research signal, not investment advice.</p>
    </div>
  );
}

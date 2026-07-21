"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { PortfolioBuilder } from "@/features/portfolios/PortfolioBuilder";
import { usePortfolio } from "@/lib/api/queries";

export default function PortfolioBuilderPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const portfolio = usePortfolio(id);

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <Link href="/portfolios" className="text-sm text-muted-foreground hover:text-foreground">
          ← Portfolios
        </Link>
        {portfolio.isLoading ? (
          <h1 className="text-2xl font-semibold tracking-tight">Loading…</h1>
        ) : portfolio.isError ? (
          <h1 className="text-2xl font-semibold tracking-tight text-destructive">Portfolio not found</h1>
        ) : (
          <>
            <h1 className="text-2xl font-semibold tracking-tight">{portfolio.data?.name}</h1>
            <p className="text-sm text-muted-foreground">
              Benchmark {portfolio.data?.benchmark} · {portfolio.data?.base_currency}
            </p>
          </>
        )}
      </header>

      {portfolio.isSuccess ? <PortfolioBuilder portfolioId={id} /> : null}
    </div>
  );
}

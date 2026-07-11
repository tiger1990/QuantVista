"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Decomposition } from "@/components/decomposition";
import { Disclaimer } from "@/components/disclaimer";
import { Card, CardContent } from "@/components/ui/card";
import { NewsList } from "@/features/news/NewsList";
import { useDecomposition, useStockDetail, useStockNews } from "@/lib/api/queries";
import { formatScore, scoreTone, toneTextClass } from "@/lib/score";

function SubScore({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="space-y-1">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`text-xl font-semibold tabular-nums ${toneTextClass(scoreTone(value))}`}>
        {formatScore(value)}
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="space-y-1">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="tabular-nums">{value == null ? "—" : value.toFixed(2)}</p>
    </div>
  );
}

function NotFound({ symbol }: { symbol: string }) {
  return (
    <Card>
      <CardContent className="space-y-2 py-12 text-center">
        <p className="text-lg font-medium">{symbol} not found</p>
        <p className="text-sm text-muted-foreground">No such stock in the universe.</p>
        <Link href="/stocks" className="inline-block text-sm text-primary hover:underline">
          Back to stocks
        </Link>
      </CardContent>
    </Card>
  );
}

export default function StockDetailPage() {
  const params = useParams<{ symbol: string }>();
  const symbol = params.symbol;
  const detail = useStockDetail(symbol);
  const decomp = useDecomposition(symbol);
  const news = useStockNews(symbol);

  if (detail.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }
  if (detail.data === null) {
    return <NotFound symbol={symbol} />;
  }
  if (detail.isError || !detail.data) {
    return <p className="text-sm text-destructive">Could not load {symbol}.</p>;
  }

  const d = detail.data;
  const s = d.snapshot;

  return (
    <div className="space-y-6">
      <Link
        href="/stocks"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Stocks
      </Link>

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-0.5">
          <h1 className="text-3xl font-semibold tracking-tight">{d.symbol}</h1>
          <p className="text-muted-foreground">{d.company_name}</p>
          <p className="text-xs text-muted-foreground">
            {[d.sector, d.industry, d.market].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Composite</p>
          <p
            className={`text-4xl font-semibold tabular-nums ${toneTextClass(scoreTone(s.composite_score))}`}
          >
            {formatScore(s.composite_score)}
          </p>
          {s.close != null ? (
            <p className="text-sm text-muted-foreground">
              ₹{s.close.toFixed(2)}
              {s.price_date ? ` · ${s.price_date}` : ""}
            </p>
          ) : null}
        </div>
      </header>

      <Card>
        <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <SubScore label="Fundamental" value={s.fundamental_score} />
          <SubScore label="Momentum" value={s.momentum_score} />
          <SubScore label="Quality" value={s.quality_score} />
          <SubScore label="Sentiment" value={s.sentiment_score} />
          <SubScore label="Risk" value={s.risk_score} />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-5">
          <Metric label="P/E" value={s.pe} />
          <Metric label="P/B" value={s.pb} />
          <Metric label="ROE" value={s.roe} />
          <Metric label="ROCE" value={s.roce} />
          <Metric label="D/E" value={s.debt_equity} />
        </CardContent>
      </Card>

      {decomp.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading decomposition…</p>
      ) : decomp.data ? (
        <Decomposition data={decomp.data} />
      ) : (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            No score decomposition yet for {symbol}.
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-3">
          <h2 className="text-sm font-semibold">Recent news</h2>
          <NewsList
            items={news.data ?? []}
            isLoading={news.isLoading}
            emptyMessage={`No recent news for ${symbol}.`}
          />
        </CardContent>
      </Card>

      <Disclaimer />
    </div>
  );
}

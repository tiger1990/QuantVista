import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";
import type { RankingItem, StockListItem } from "@/lib/api/queries";
import { type ScoreTone, formatScore, scoreTone, toneTextClass } from "@/lib/score";
import { cn } from "@/lib/utils";

function Stat({ label, value, tone }: { label: string; value: string; tone?: ScoreTone }) {
  return (
    <div className="space-y-1">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("text-2xl font-semibold tabular-nums", tone && toneTextClass(tone))}>{value}</p>
    </div>
  );
}

/** Hero KPI strip — avg composite, coverage, count, as-of. */
export function MarketOverview({ items, asOf }: { items: RankingItem[]; asOf?: string | null }) {
  const scored = items.filter((i) => i.composite_score != null);
  const avg = scored.length
    ? scored.reduce((a, i) => a + (i.composite_score ?? 0), 0) / scored.length
    : null;
  const cov = scored.length
    ? scored.reduce((a, i) => a + (i.coverage ?? 0), 0) / scored.length
    : null;

  return (
    <Card>
      <CardContent className="grid grid-cols-2 gap-6 sm:grid-cols-4">
        <Stat label="Avg composite" value={formatScore(avg)} tone={scoreTone(avg)} />
        <Stat label="Coverage" value={cov == null ? "—" : `${Math.round(cov * 100)}%`} />
        <Stat label="Scored" value={String(scored.length)} />
        <Stat label="As of" value={asOf ?? "—"} />
      </CardContent>
    </Card>
  );
}

/** Top-N leaderboard tile. */
export function TopRanked({ items }: { items: RankingItem[] }) {
  const top = items.slice(0, 6);
  return (
    <Card className="h-full">
      <CardContent className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Top ranked</h2>
          <Link href="/rankings" className="text-xs text-primary hover:underline">
            View all
          </Link>
        </div>
        {top.length ? (
          <ol className="space-y-1.5">
            {top.map((i) => (
              <li key={i.symbol} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2">
                  <span className="w-4 tabular-nums text-muted-foreground">{i.rank}</span>
                  <span className="font-medium">{i.symbol}</span>
                </span>
                <span className={cn("tabular-nums", toneTextClass(scoreTone(i.composite_score)))}>
                  {formatScore(i.composite_score)}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">No rankings yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function toneBg(tone: ScoreTone): string {
  return tone === "positive"
    ? "bg-positive/15 border-positive/30"
    : tone === "negative"
      ? "bg-negative/15 border-negative/30"
      : "bg-muted border-border";
}

/** Sector heatmap — tiles colored by each sector's average composite. */
export function SectorHeatmap({ stocks }: { stocks: StockListItem[] }) {
  const bySector = new Map<string, number[]>();
  for (const s of stocks) {
    if (s.sector && s.composite_score != null) {
      const list = bySector.get(s.sector) ?? [];
      list.push(s.composite_score);
      bySector.set(s.sector, list);
    }
  }
  const tiles = [...bySector.entries()]
    .map(([sector, scores]) => ({
      sector,
      avg: scores.reduce((a, b) => a + b, 0) / scores.length,
      n: scores.length,
    }))
    .sort((a, b) => b.avg - a.avg);

  return (
    <Card className="h-full">
      <CardContent className="space-y-3">
        <h2 className="text-sm font-semibold">Sectors</h2>
        {tiles.length ? (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {tiles.map((t) => (
              <div key={t.sector} className={cn("rounded-md border p-3", toneBg(scoreTone(t.avg)))}>
                <p className="truncate text-xs font-medium" title={t.sector}>
                  {t.sector}
                </p>
                <p className="mt-1 text-lg font-semibold tabular-nums">{formatScore(t.avg)}</p>
                <p className="text-[11px] text-muted-foreground">{t.n} stocks</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">No scored sectors yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

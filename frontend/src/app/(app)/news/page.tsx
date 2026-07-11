"use client";

import { Disclaimer } from "@/components/disclaimer";
import { Card, CardContent } from "@/components/ui/card";
import { NewsList } from "@/features/news/NewsList";
import { useLatestNews } from "@/lib/api/queries";

export default function NewsPage() {
  const news = useLatestNews(40);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Financial News</h1>
        <p className="text-sm text-muted-foreground">
          Latest India-market headlines, aggregated from multiple sources.
        </p>
      </header>

      {news.isError ? (
        <p className="py-10 text-center text-sm text-destructive">Could not load news.</p>
      ) : (
        <Card>
          <CardContent>
            <NewsList
              items={news.data ?? []}
              isLoading={news.isLoading}
              emptyMessage="No news yet — run the news ingestion job."
            />
          </CardContent>
        </Card>
      )}

      <Disclaimer />
    </div>
  );
}

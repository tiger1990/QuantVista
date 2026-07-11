"use client";

import { ExternalLink } from "lucide-react";

import type { NewsItem } from "@/lib/api/queries";
import { relativeTime } from "@/lib/utils";

/**
 * Safe news list (QV-043). Headline + summary are plain text → React escapes them (no
 * dangerouslySetInnerHTML). The source link opens in a new tab with rel="noopener noreferrer".
 */
export function NewsList({
  items,
  isLoading,
  emptyMessage = "No recent news.",
}: {
  items: NewsItem[];
  isLoading?: boolean;
  emptyMessage?: string;
}) {
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading news…</p>;
  if (!items.length) return <p className="text-sm text-muted-foreground">{emptyMessage}</p>;

  return (
    <ul className="divide-y divide-border">
      {items.map((n) => (
        <li key={n.id} className="py-3 first:pt-0 last:pb-0">
          <a
            href={n.source_url ?? "#"}
            target="_blank"
            rel="noopener noreferrer"
            className="group block"
          >
            <p className="text-sm font-medium leading-snug group-hover:text-primary">
              {n.headline}
              <ExternalLink className="ml-1 inline size-3 opacity-0 transition-opacity group-hover:opacity-60" />
            </p>
            {n.summary ? (
              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{n.summary}</p>
            ) : null}
            <p className="mt-1 text-[11px] text-muted-foreground">
              {[n.source, relativeTime(n.published_at)].filter(Boolean).join(" · ")}
            </p>
          </a>
        </li>
      ))}
    </ul>
  );
}

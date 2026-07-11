"use client";

import { Newspaper } from "lucide-react";

import type { NewsItem } from "@/lib/api/queries";

/**
 * Horizontal marquee of latest headlines for the Overview (QV-043). Pauses on hover; each headline
 * links out (rel="noopener"). Purely presentational — reduced-motion users get a static, scrollable
 * row (the animation is decorative, content stays reachable).
 */
export function NewsTicker({ items }: { items: NewsItem[] }) {
  if (!items.length) return null;

  return (
    <div className="flex items-center gap-3 overflow-hidden rounded-lg border border-border bg-card px-3 py-2">
      <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Newspaper className="size-3.5" />
        News
      </span>
      <div className="group relative flex-1 overflow-hidden">
        <div className="flex w-max gap-8 whitespace-nowrap motion-safe:animate-[ticker_60s_linear_infinite] group-hover:[animation-play-state:paused]">
          {[...items, ...items].map((n, idx) => (
            <a
              key={`${n.id}-${idx}`}
              href={n.source_url ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-foreground/80 hover:text-primary"
            >
              <span className="text-muted-foreground">{n.source ?? "News"}</span> · {n.headline}
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}

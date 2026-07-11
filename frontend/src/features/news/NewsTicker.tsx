"use client";

import { Newspaper } from "lucide-react";

import type { NewsItem } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

/**
 * Continuous right-to-left news marquee for the Overview (QV-043). Headlines scroll slowly (120s
 * loop) so they're readable as they pass, and the row pauses on hover so you can finish reading or
 * click through. Content is duplicated in the DOM so the -50% loop is seamless. Purely
 * presentational — reduced-motion users get a static, scrollable row (the motion is decorative).
 */
export function NewsTicker({ items, className }: { items: NewsItem[]; className?: string }) {
  if (!items.length) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-3 overflow-hidden rounded-lg border border-border bg-card px-3 py-2",
        className,
      )}
    >
      <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Newspaper className="size-3.5" />
        News
      </span>
      <div className="relative flex-1 overflow-hidden">
        <div className="ticker-track flex w-max gap-8 whitespace-nowrap">
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

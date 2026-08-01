import Link from "next/link";

import { DISCLAIMER } from "@/lib/disclaimer";
import { cn } from "@/lib/utils";

/**
 * The research-only, non-advice disclaimer shown on every data surface.
 *
 * The text comes from the shared constant mirroring the API's `DISCLAIMER`, so the compliance line
 * has one source rather than a copy per surface. The Methodology link satisfies `07` §1.5
 * (published methodology): this component already renders on every score surface, so linking here
 * covers them all rather than editing each page.
 */
export function Disclaimer({ className }: { className?: string }) {
  return (
    <p className={cn("text-xs text-muted-foreground", className)}>
      {DISCLAIMER}{" "}
      <Link href="/methodology" className="underline underline-offset-2 hover:text-foreground">
        Methodology
      </Link>
    </p>
  );
}

import { cn } from "@/lib/utils";

/** The research-only, non-advice disclaimer shown on every data surface. */
export function Disclaimer({ className }: { className?: string }) {
  return (
    <p className={cn("text-xs text-muted-foreground", className)}>
      Research signal, not investment advice.
    </p>
  );
}

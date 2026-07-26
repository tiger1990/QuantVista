"use client";

import { Button } from "@/components/ui/button";
import { useApplyTargets } from "@/lib/api/queries";

/** Persist a set of optimizer `weights` (stock_id → Decimal-string) as each position's
 * target_weight. Closes the loop: optimize → set targets → monitor drift. */
export function SetTargetsButton({
  portfolioId,
  weights,
}: {
  portfolioId: string;
  weights: Record<string, string>;
}) {
  const applyTargets = useApplyTargets(portfolioId);
  const targets = Object.entries(weights).map(([stock_id, target_weight]) => ({
    stock_id,
    target_weight,
  }));

  const apply = () => {
    if (targets.length === 0) return;
    if (!window.confirm("Set these optimized weights as your target weights?")) return;
    applyTargets.mutate(targets);
  };

  return (
    <Button
      type="button"
      variant="outline"
      onClick={apply}
      disabled={applyTargets.isPending || targets.length === 0}
    >
      {applyTargets.isPending ? "Setting…" : "Set as targets"}
    </Button>
  );
}

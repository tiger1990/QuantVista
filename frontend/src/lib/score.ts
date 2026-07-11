export type ScoreTone = "positive" | "neutral" | "negative";

/** Bucket a 0–100 composite into a semantic tone (drives heatmap + score-cell color). */
export function scoreTone(score: number | null | undefined): ScoreTone {
  if (score == null) return "neutral";
  if (score >= 60) return "positive";
  if (score < 40) return "negative";
  return "neutral";
}

/** One-decimal score, or an em dash when unscored. */
export function formatScore(score: number | null | undefined, digits = 1): string {
  return score == null ? "—" : score.toFixed(digits);
}

/** Coverage as a whole percent. The API already returns 0–100 (like the scores) — do NOT ×100. */
export function formatCoverage(coverage: number | null | undefined): string {
  return coverage == null ? "—" : `${Math.round(coverage)}%`;
}

/** Rupee price to 2dp with Indian digit grouping (₹1,10,000.00), or an em dash when no price. */
export function formatPrice(close: number | null | undefined): string {
  return close == null
    ? "—"
    : `₹${close.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Tailwind text-color class for a tone (semantic tokens, not decorative). */
export function toneTextClass(tone: ScoreTone): string {
  return tone === "positive"
    ? "text-positive"
    : tone === "negative"
      ? "text-negative"
      : "text-muted-foreground";
}

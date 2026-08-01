import type { Metadata } from "next";
import Link from "next/link";

import { DISCLAIMER } from "@/lib/disclaimer";
import {
  BACKTEST_WEIGHTS_VERSION,
  CATEGORY_WEIGHTS,
  COSTS_BPS_MAX,
  MODEL_VERSION,
  REBALANCE_CADENCES,
  SCORING_WEIGHTS_VERSION,
  SLIPPAGE_BPS,
  WINSOR_HI_PCT,
  WINSOR_LO_PCT,
} from "@/lib/methodology";

export const metadata: Metadata = {
  title: "Methodology & Disclaimer · QuantVista",
  description:
    "How QuantVista computes factor scores and backtests: normalisation, weights, point-in-time and survivorship controls, cost assumptions, and the research-only posture.",
};

/**
 * Public methodology page (QV-070). Deliberately OUTSIDE the `(app)` route group: that layout
 * redirects anonymous users to /login, and a trust page behind auth is invisible to exactly the
 * people it exists to convince. Server-rendered prose — no auth, no client state.
 */
export default function MethodologyPage() {
  return (
    <div className="min-h-dvh">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-3xl items-baseline justify-between px-6 py-4">
          <Link href="/" className="font-semibold tracking-tight hover:text-primary">
            QuantVista
          </Link>
          <Link href="/" className="text-xs text-muted-foreground hover:text-foreground">
            Back to app
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="text-3xl font-semibold tracking-tight">Methodology &amp; Disclaimer</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          This page documents how every number on this platform is produced — how factor scores are
          normalised and blended, how history is read, what a backtest assumes, and what the results
          do and do not mean. It is written to be checkable: each figure below is the value the
          engine actually uses, and a test fails the build if this page drifts from the code.
        </p>

        <Section id="posture" title="What this is — and is not">
          <p>
            QuantVista is a <Strong>research tool</Strong>. {DISCLAIMER} Specifically:
          </p>
          <ul className="mt-3 space-y-2">
            <Bullet>
              <Strong>Nothing here is personalised.</Strong> Scores, rankings and optimisations are
              computed from public data and parameters you choose. They are never derived from your
              financial situation, risk profile or goals, and no output is a judgement that an
              instrument is suitable for you.
            </Bullet>
            <Bullet>
              <Strong>The language is deliberate.</Strong> You will see &ldquo;research
              signal&rdquo;, &ldquo;factor score&rdquo; and &ldquo;screened candidates&rdquo; — not
              &ldquo;we recommend you buy&rdquo;. That distinction is the product, not a formality.
            </Bullet>
            <Bullet>
              <Strong>No execution, custody or brokerage.</Strong> The platform does not place
              orders or hold assets.
            </Bullet>
            <Bullet>
              <Strong>Past performance does not indicate future results.</Strong> Backtests are
              simulations over historical data with modelled assumptions, not achieved returns.
            </Bullet>
          </ul>
        </Section>

        <Section id="scoring" title="How scores are computed">
          <p>
            Each factor produces a raw value from point-in-time data. Raw values are not comparable
            across companies or sectors, so every factor goes through the same four steps:
          </p>
          <ol className="mt-3 space-y-2">
            <Step n={1}>
              <Strong>Direction-adjust</Strong> — the raw value is oriented so that higher is always
              better, whichever way the underlying metric runs.
            </Step>
            <Step n={2}>
              <Strong>Winsorize</Strong> to the sector&rsquo;s {WINSOR_LO_PCT}
              <sup>st</sup>–{WINSOR_HI_PCT}
              <sup>th</sup> percentile band, before standardising. A handful of extreme filings
              would otherwise distort the mean and standard deviation for everyone in that sector.
            </Step>
            <Step n={3}>
              <Strong>Sector z-score</Strong> — standardised against sector peers, so a company is
              measured against comparable businesses rather than the whole market. A sector with no
              dispersion (or a single member) yields a neutral 0 rather than a spurious extreme.
            </Step>
            <Step n={4}>
              <Strong>Rank to percentiles</Strong> — a 0–100 percentile within the sector, and a
              second percentile across the whole universe.
            </Step>
          </ol>

          <p className="mt-5">
            Category scores are then blended into the composite using fixed, published weights
            (weight set <Mono>{SCORING_WEIGHTS_VERSION}</Mono>):
          </p>
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-1.5 font-medium">Category</th>
                <th className="py-1.5 text-right font-medium">Weight</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {CATEGORY_WEIGHTS.map((w) => (
                <tr key={w.category} className="border-b border-border/60">
                  <td className="py-1.5">{w.category}</td>
                  <td className="py-1.5 text-right">{(w.weight * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-4">
            Coverage is tracked per company: a name with <Strong>no</Strong> usable factor data
            receives no score at all rather than an imputed one, so a sparsely-covered company never
            appears artificially average. The methodology carries a version,{" "}
            <Mono>{MODEL_VERSION}</Mono>, which is bumped on any change to the pipeline or weights —
            scores computed under different versions are not directly comparable.
          </p>
        </Section>

        <Section id="point-in-time" title="Point-in-time and survivorship controls">
          <p>
            The two classic ways a backtest flatters itself are using information that was not
            available at the time, and testing only on companies that still exist today. Both are
            prevented structurally here, not by convention:
          </p>
          <ul className="mt-3 space-y-2">
            <Bullet>
              <Strong>Point-in-time reads.</Strong> Historical data is read through a seam bounded
              by the simulation date. Fundamentals are visible only from the date they became
              knowable, not the period they describe — a result published in May does not influence
              a decision dated March.
            </Bullet>
            <Bullet>
              <Strong>Survivorship-free universe.</Strong> Index membership is reconstructed as it
              stood on each date. A company later delisted or dropped from the index is still held
              on the dates it was a member, and is exited at its last available price rather than
              vanishing from the simulation.
            </Bullet>
            <Bullet>
              <Strong>Enforced by the build.</Strong> A permanent, non-skippable test suite
              constructs counterfactual scenarios and fails the build if either bias reappears. It
              is not possible to merge a change that reintroduces look-ahead or survivorship bias
              without the test suite objecting.
            </Bullet>
          </ul>
        </Section>

        <Section id="backtests" title="What a backtest assumes">
          <p>Every simulated result on this platform is produced under these assumptions:</p>
          <ul className="mt-3 space-y-2">
            <Bullet>
              <Strong>Equal weighting</Strong> ({<Mono>{BACKTEST_WEIGHTS_VERSION}</Mono>}) across
              the selected names — no position sizing, no leverage, no shorting.
            </Bullet>
            <Bullet>
              <Strong>Rebalancing</Strong> at your chosen cadence ({REBALANCE_CADENCES.join(", ")}),
              holding between rebalance dates.
            </Bullet>
            <Bullet>
              <Strong>Adjusted-close returns</Strong>, so splits and similar corporate actions do
              not appear as gains or losses.
            </Bullet>
            <Bullet>
              <Strong>Costs</Strong> — your commission assumption (up to {COSTS_BPS_MAX} bps) plus a
              fixed <Strong>{SLIPPAGE_BPS} bps slippage</Strong> charge, applied to each unit of
              turnover traded at every rebalance. Costs are modelled, not observed: real fills,
              impact and taxes will differ.
            </Bullet>
          </ul>

          <Caveat title="The benchmark is a proxy, not the published index">
            The comparison line is an <Strong>equal-weight buy-and-hold of the universe</Strong> as
            it stood on your start date — computed internally on the same price discipline as the
            strategy. It is <Strong>not</Strong> the licensed Nifty 200 Total Return Index, which
            requires a data licence we have not taken. Do not read the benchmark figure as the
            index&rsquo;s published return; read it as a like-for-like passive baseline.
          </Caveat>

          <Caveat title="Results depend on ingested data coverage">
            A backtest can only see the price and factor history that has been ingested. A date
            range that falls outside that coverage produces a{" "}
            <Strong>degenerate, all-zero result</Strong> — a flat curve and zeroed metrics — rather
            than an error. If a result looks empty, check the range against the available history
            before reading anything into it.
          </Caveat>
        </Section>

        <Section id="reproducibility" title="Reproducibility">
          <p>
            Every backtest result carries a <Strong>reproducibility fingerprint</Strong>: a SHA-256
            of the canonical specification together with the scoring-model and weighting versions.
            Two runs sharing a fingerprint were produced by an identical recipe — same settings,
            same methodology version — which is what makes a result auditable rather than merely
            repeatable-looking.
          </p>
          <Caveat title="The fingerprint covers the recipe, not the data">
            It does <Strong>not</Strong> hash the underlying price or factor data. The same
            fingerprint can produce different numbers if the ingested history changed between runs —
            for example after a backfill or a corporate-action correction. It answers &ldquo;was
            this computed the same way?&rdquo;, not &ldquo;was this computed on the same
            data?&rdquo;.
          </Caveat>
          <p className="mt-4">
            The fingerprint is returned by the API and stored with each run&rsquo;s metrics. It is
            not shown in the results view, where an unexplained hash reads as noise.
          </p>
        </Section>

        <footer className="mt-12 border-t border-border pt-5">
          <p className="text-xs leading-relaxed text-muted-foreground">
            {DISCLAIMER} QuantVista provides research tooling and does not provide investment
            advice, personalised recommendations, or execution services. Simulated results are not
            achieved returns, and past performance does not indicate future results. Verify any
            figure independently before acting on it.
          </p>
        </footer>
      </main>
    </div>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className="mt-10 border-t border-border pt-8">
      <h2 id={`${id}-heading`} className="text-lg font-semibold tracking-tight">
        {title}
      </h2>
      <div className="mt-3 space-y-1 text-sm leading-relaxed text-muted-foreground">{children}</div>
    </section>
  );
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <li className="border-l-2 border-border pl-3 leading-relaxed">
      <span className="[&>strong]:text-foreground">{children}</span>
    </li>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 leading-relaxed">
      <span className="mt-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
        {String(n).padStart(2, "0")}
      </span>
      <span className="[&>strong]:text-foreground">{children}</span>
    </li>
  );
}

function Caveat({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <aside className="mt-5 rounded-md border border-border bg-muted/30 px-4 py-3">
      <p className="text-[11px] font-medium uppercase tracking-widest text-foreground">{title}</p>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground [&>strong]:text-foreground">
        {children}
      </p>
    </aside>
  );
}

function Strong({ children }: { children: React.ReactNode }) {
  return <strong className="font-medium text-foreground">{children}</strong>;
}

function Mono({ children }: { children: React.ReactNode }) {
  return <code className="font-mono text-[13px] text-foreground">{children}</code>;
}

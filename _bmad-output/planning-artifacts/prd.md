# QuantVista — PRD (canonical for BMAD)

> **Authoritative source:** `plans/01-prd.md` (+ `plans/00-overview-and-decisions.md` for the decision
> log). This file is the BMAD-canonical copy so Phase-3 tooling (Implementation Readiness) can discover
> and analyze it. Keep substantive edits in `plans/01-prd.md` and mirror requirement-bearing changes here.
>
> **Scope:** v1 = India (Nifty 200), research/analytics SaaS, freemium tiers. **Research, not advice** (D1).

## 1. Problem & opportunity

Retail and semi-professional Indian investors stop at PE/PB/promoter holding. Institutional multi-factor
analysis, optimization, and disciplined backtesting are locked behind Bloomberg/FactSet-class tooling.
QuantVista delivers a transparent, explainable subset for Nifty 200 at SaaS price points — a "quant
research cockpit" for serious retail, analysts, and small family offices.

## 2. Personas

| Persona | Description | Jobs-to-be-done | Tier |
|---------|-------------|-----------------|------|
| Asha — self-directed investor | Manages own portfolio | Screen by factors, sanity-check holdings, alerts | Free → Pro |
| Ravi — research analyst | Boutique/PMS, builds theses | Deep factor & news analysis, comparisons, export | Pro |
| Meera — quant/PM | Builds & validates strategies | Custom weights, optimization, backtesting, API | Quant |
| Sam — family office associate | Multiple mandates | Multi-portfolio risk monitoring, rebalancing | Quant |

**Anti-persona (v1):** anyone seeking personalized buy/sell advice for a fee (→ `future-ria-compliance.md`).

## 3. Product pillars

- **A · Stock Intelligence** — daily per-stock scores (Fundamental, Momentum, Quality, Sentiment, Risk) +
  Composite; full factor decomposition ("why this score"); historical trends + sector/universe percentiles.
- **B · Screener & Comparison** — filter/sort across factors/fundamentals/ownership/technicals; side-by-side
  comparison; saved screens (entitlement-limited).
- **C · News & Sentiment** — per-stock news with FinBERT sentiment + event-impact score; sentiment as a
  scoring input.
- **D · Portfolio Construction & Risk** — build manually or from ranked universe; optimize (MVO → Risk
  Parity → Black-Litterman/HRP); risk analytics (beta, vol, drawdown, Sharpe/Sortino, exposure,
  concentration); rebalancing + drift alerts.
- **E · Backtesting** — survivorship- and look-ahead-bias-controlled; standard metrics; Nifty 200 TRI benchmark.
- **F · Alerts** — threshold/news/digest alerts; in-app + email (v1), webhook/Slack (Quant, later).

## 4. Freemium tiers & entitlements (D5)

Pricing TBD (O3); structure is fixed. Centralized **Entitlement Service** returns limits/flags; enforced
in API + surfaced in UI; **no per-tier feature gate is hard-coded** — gates read entitlements.

| Capability | Free | Pro | Quant |
|---|---|---|---|
| Scores & decomposition | Top-50 | Full universe | Full universe + raw factor data |
| Saved screens | 3 | 25 | Unlimited |
| Watchlists | 1 (≤10 stocks) | 10 | Unlimited |
| Portfolios | 1 | 5 | Unlimited |
| Optimization | — | MVO + Risk Parity | + BL/HRP, custom weights |
| Backtesting | — | Limited (1y, presets) | Full |
| Alerts | 3 | 50 | Unlimited + webhooks |
| News/sentiment history | 7 days | 1 year | Full |
| Public/REST API | — | — | Yes (rate-limited) |
| CSV export | — | Yes | Yes + bulk |

## 5. Representative user stories + acceptance criteria

- **US-01 (Screener):** filter Nifty 200 (ROE>15% & Composite>70), sort by Momentum.
  **AC:** full-universe results <1s; rows link to detail; filter state shareable via URL.
- **US-02 (Score explainability):** Composite breaks into factor contributions + inputs as-of a date.
  **AC:** decomposition sums to composite; every input shows its as-of date (PIT); no future data.
- **US-03 (Portfolio optimize):** optimize 15-stock portfolio under 25% sector cap + target vol.
  **AC:** weights sum to 100%; constraints respected or clear infeasibility message.
- **US-04 (Backtest integrity):** backtests exclude look-ahead & survivorship bias.
  **AC:** delisted constituents included historically; signals use only PIT data; documented methodology.
- **US-05 (Alert):** alert when a holding's Composite drops below 50.
  **AC:** fires within one scoring cycle; deduplicated; honors tier limits.
- **US-06 (Entitlement):** Free user creating a 2nd portfolio sees an upgrade prompt.
  **AC:** server returns structured `entitlement_exceeded`; UI shows upgrade CTA.

## 6. Non-functional requirements

| Area | Target (v1) |
|---|---|
| API latency (read p95) | <300 ms cached score/stock; <1 s screener over full universe |
| Availability | 99.5% single-region → 99.9% multi-AZ at scale |
| Data freshness | EOD prices & scores before next IST open; news ~15 min of ingest |
| Pipeline correctness | Idempotent, replayable, PIT-correct |
| Security | RLS tenant isolation; OWASP ASVS L2 |
| Privacy | India DPDP Act 2023 alignment |
| Scalability | 10k tenants / 100k MAU on modular monolith before extraction |
| Observability | RED/USE metrics, traces, structured logs, actionable alerts |

## 7. Non-goals (v1)

No personalized advice/suitability; no order execution/brokerage; no intraday/real-time/live signals
(EOD focus); no US/global markets; no native mobile (responsive web first); no options/F&O analytics.

## 8. Success metrics

North Star: **Weekly Active Research Sessions per paying tenant.** Supporting: Free→Pro conversion,
screens/portfolios/backtests per WAU, 4-week paid retention, decomposition-view & methodology-page rates,
pipeline success & data-freshness SLO attainment.

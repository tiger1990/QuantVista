# 01 — Product Requirements (PRD)

> **Scope:** v1 = India (Nifty 200), research/analytics SaaS, freemium tiers.
> See `00-overview-and-decisions.md` for the decision log.

---

## 1. Problem & opportunity

Retail and semi-professional Indian investors stop at PE, PB, and promoter holding. Institutional-grade
multi-factor analysis, portfolio optimization, and disciplined backtesting are locked behind Bloomberg/
FactSet-class tooling priced for institutions. QuantVista delivers a transparent, explainable subset of
that capability for Nifty 200 at SaaS price points.

**Opportunity:** a credible "quant research cockpit" for serious retail, analysts, and small family offices —
with a clean upgrade path to regulated advisory and US coverage.

---

## 2. Target users & personas

| Persona | Description | Primary jobs-to-be-done | Tier fit |
|---------|-------------|--------------------------|----------|
| **Self-directed investor (Asha)** | Experienced retail investor, manages own portfolio | Screen by factors, sanity-check holdings, get alerts | Free → Pro |
| **Research analyst (Ravi)** | Works at a boutique/PMS, builds theses | Deep factor & news analysis, comparisons, export | Pro |
| **Quant/PM (Meera)** | Builds & validates strategies | Custom factor weights, optimization, backtesting, API | Quant |
| **Family office associate (Sam)** | Manages multiple mandates | Multi-portfolio risk monitoring, rebalancing | Quant |

Anti-persona (v1): anyone seeking **personalized buy/sell advice for a fee** — out of scope until
`future-ria-compliance.md` is executed.

---

## 3. Product pillars & capabilities

### Pillar A — Stock Intelligence
- Daily per-stock scores: **Fundamental, Momentum, Quality, Sentiment, Risk**, and a **Composite signal**.
- Full factor decomposition ("why this score") for explainability.
- Historical score trends and percentile ranks within sector & universe.

### Pillar B — Screener & Comparison
- Filter/sort across all factors, fundamentals, ownership, technicals.
- Side-by-side comparison of up to N stocks.
- Saved screens (entitlement-limited by tier).

### Pillar C — News & Sentiment Intelligence
- Per-stock news feed with sentiment label/score (FinBERT) and an event-impact score.
- Sentiment trend over time; sentiment as a scoring input.

### Pillar D — Portfolio Construction & Risk
- Build portfolios manually or from a ranked universe.
- Optimize allocation (Mean-Variance → Risk Parity → Black-Litterman / HRP across phases).
- Risk analytics: beta, volatility, drawdown, Sharpe/Sortino, sector exposure, concentration.
- Rebalancing suggestions and portfolio drift alerts.

### Pillar E — Backtesting
- Backtest factor strategies and portfolios with **survivorship- and look-ahead-bias controls**.
- Standard performance & risk metrics, benchmark comparison (Nifty 200 TRI).

### Pillar F — Alerts
- Threshold alerts (score, PE, RSI, drift), news-event alerts, scheduled digests.
- Channels: in-app, email (v1); webhook/Slack (Quant tier, later).

---

## 4. Freemium tiers & entitlements (D5)

Pricing TBD (O3); **structure** is fixed so entitlements can be built now.

| Capability | Free | Pro | Quant |
|------------|------|-----|-------|
| Universe coverage | Nifty 200 (delayed/EOD) | Nifty 200 (EOD) | Nifty 200 (EOD) + raw factor data |
| Stock scores & decomposition | Top-50 only | Full universe | Full universe |
| Saved screens | 3 | 25 | Unlimited |
| Watchlists | 1 (max 10 stocks) | 10 | Unlimited |
| Portfolios | 1 | 5 | Unlimited |
| Optimization | — | MVO + Risk Parity | + Black-Litterman / HRP, custom factor weights |
| Backtesting | — | Limited (1y, presets) | Full (custom range & strategy) |
| Alerts | 3 | 50 | Unlimited + webhooks |
| News/sentiment history | 7 days | 1 year | Full |
| Public/REST API | — | — | Yes (rate-limited) |
| Data export (CSV) | — | Yes | Yes + bulk |

**Entitlement enforcement:** centralized Entitlement Service reads the tenant's plan and returns
limits/flags; enforced in the API layer and surfaced in the UI. No feature gate is hard-coded per tier;
gates read entitlements. (See `02` and `04`.)

---

## 5. Representative user stories (with acceptance criteria)

> Format: *As a … I want … so that …* + **AC**. IDs feed the backlog in `09`.

- **US-01 (Screener):** As Asha, I want to filter Nifty 200 by ROE > 15% and Composite > 70 and sort by
  Momentum, so I can find quality-momentum names.
  **AC:** results return < 1s for the full universe; each row links to detail; filter state is shareable via URL.
- **US-02 (Score explainability):** As Ravi, I want to see how a stock's Composite breaks into factor
  contributions and the underlying inputs as of a date, so I can trust it.
  **AC:** decomposition sums to the composite; every input shows its as-of date (PIT); no future data.
- **US-03 (Portfolio optimize):** As Meera, I want to optimize a 15-stock portfolio under a 25% sector cap
  and target volatility, so allocation reflects my constraints.
  **AC:** optimizer returns weights summing to 100%; constraints respected or a clear infeasibility message.
- **US-04 (Backtest integrity):** As Meera, I want backtests that exclude look-ahead and survivorship bias,
  so results are credible.
  **AC:** delisted constituents included historically; signals use only PIT data; documented methodology.
- **US-05 (Alert):** As Asha, I want an alert when any holding's Composite drops below 50, so I can react.
  **AC:** alert fires within one scoring cycle of the breach; deduplicated; honors tier limits.
- **US-06 (Entitlement):** As a Free user, when I try to create a 2nd portfolio I see an upgrade prompt.
  **AC:** server rejects with a structured `entitlement_exceeded` error; UI shows upgrade CTA.

---

## 6. Non-functional requirements (NFRs)

| Area | Target (v1) |
|------|-------------|
| API latency (read, p95) | < 300 ms for cached score/stock reads; < 1 s for screener over full universe |
| Availability | 99.5% (single-region) → 99.9% with multi-AZ at scale |
| Data freshness | EOD prices & scores available before next market open (IST); news within ~15 min of ingest |
| Pipeline correctness | Idempotent, replayable, PIT-correct (see `03`/`06`) |
| Security | Tenant isolation via RLS; OWASP ASVS L2 baseline (see `07`) |
| Privacy | India **DPDP Act 2023** alignment for user PII (see `07`) |
| Scalability | 10k tenants / 100k MAU on modular monolith before service extraction |
| Observability | RED/USE metrics, traces, structured logs, actionable alerts (see `08`) |

---

## 7. Explicit non-goals (v1)

- No personalized investment advice or suitability (→ `future-ria-compliance.md`).
- No order execution / brokerage integration.
- No intraday/real-time tick data or live trading signals (EOD focus).
- No US/global markets (→ `future-us-market-expansion.md`).
- No mobile native apps (responsive web first).
- No options/derivatives/F&O analytics.

---

## 8. Success metrics (North Star + supporting)

- **North Star:** Weekly Active Research Sessions per paying tenant (depth of real use).
- **Acquisition:** Free signups; Free→Pro conversion %.
- **Engagement:** screens run, portfolios built, backtests run per WAU.
- **Retention:** 4-week paid retention; alert-driven return visits.
- **Trust/quality:** score-decomposition view rate; backtest methodology page views; support tickets re: data accuracy (lower is better).
- **Reliability:** pipeline success rate; data-freshness SLO attainment.

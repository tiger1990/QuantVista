# QuantVista — Sprint Backlog

Ticket-ready expansion of `../09-roadmap-and-delivery.md`. Each sprint is a 2-week iteration for the funded
team (5–7 eng across Platform, Data, Quant, Backend, Frontend, Product/Design+Compliance — see `09` §1).

## Sprint index

| Sprint | Theme | Phase (09) | Exit gate |
|--------|-------|-----------|-----------|
| [00](sprint-00-foundations.md) | Foundations & scaffolding | 0 | Auth + tenant context in staging; CI green |
| [01](sprint-01-data-backbone-i.md) | Data backbone I — prices & ingestion | 1 | EOD prices ingested idempotently for Nifty 200 |
| [02](sprint-02-data-backbone-ii.md) | Data backbone II — fundamentals (PIT) & indicators | 1 | Bitemporal fundamentals + indicators computed |
| [03](sprint-03-stock-intelligence.md) | Stock Intelligence — scoring & UI | 1 | **MVP-internal: Nifty 200 scored daily, explainable in UI** |
| [04](sprint-04-screener-news.md) | Screener + News ingestion | 2 | Screen + saved screens + news feed |
| [05](sprint-05-sentiment-alerts.md) | Sentiment + Alerts | 2 | Sentiment in scores; alerts deliver |
| [06](sprint-06-portfolio-i.md) | Portfolio I — build & MVO optimize | 3 | Build → optimize a portfolio |
| [07](sprint-07-portfolio-ii-risk.md) | Portfolio II — Risk Parity, risk, rebalance | 3 | Risk dashboard + rebalancing |
| [08](sprint-08-backtesting-i.md) | Backtesting I — engine & bias controls | 4 | Bias-controlled async backtest runs |
| [09](sprint-09-backtesting-ii.md) | Backtesting II — Parquet, metrics, methodology | 4 | Reproducible backtests in product |
| [10](sprint-10-monetization.md) | Monetization — **M-DATA cutover** + Stripe | 5 | Licensed data + billing + gating live |
| [11](sprint-11-launch-hardening.md) | Launch hardening — security, DPDP, SLOs | 5 | **PAID LAUNCH** |
| [12](sprint-12-ml-augmentation.md) | ML augmentation (post-launch) | 6 | ML signal labeled & monitored |

## Ticket ID scheme

`QV-###` — globally sequential across the backlog (QV-001 … QV-1xx). Grouped under **Epics** (`EPIC-*`).
IDs are stable; do not renumber. New mid-stream work appends the next free number.

## Epics

| Epic | Title | Sprints |
|------|-------|---------|
| EPIC-PLAT | Platform, CI/CD, IaC, observability | 0, 11 |
| EPIC-IDN | Identity, tenancy, entitlements, billing | 0, 10 |
| EPIC-DATA | Market-data ingestion & correctness | 1, 2, 10 |
| EPIC-INTEL | Factors, scoring, intelligence APIs/UI | 3, 4 |
| EPIC-NEWS | News & sentiment | 4, 5 |
| EPIC-ALERT | Alerts & notifications | 5 |
| EPIC-PORT | Portfolio & risk | 6, 7 |
| EPIC-BT | Backtesting | 8, 9 |
| EPIC-ML | ML augmentation | 12 |
| EPIC-COMP | Compliance content & data licensing | 0, 9, 10, 11 |

## Ticket format

```
### QV-001 — <title>   `[AREA]` · `Npts` · Epic: EPIC-X · depends: QV-00x | —
**Story:** As a <role>, I want <capability>, so that <value>.
**Acceptance criteria:**
- <testable AC 1>
- <testable AC 2>
**Notes:** <design pointers, links to plan docs>
```

- **AREA tags:** `[PLAT]` `[DATA]` `[QUANT]` `[BE]` `[FE]` `[PROD]` `[SEC]`
- **Points:** Fibonacci (1, 2, 3, 5, 8, 13). 13 = should be split.
- **Definition of Done:** every ticket inherits the DoD in `../09-roadmap-and-delivery.md` §4 (tests ≥80%,
  RLS/authz + bias tests where relevant, migrations expand/contract, observability, security, docs,
  disclaimers on research surfaces). Not repeated per ticket.

## Conventions

- A sprint's tickets are pullable in parallel across workstreams unless `depends:` says otherwise.
- Cross-sprint dependencies are explicit; nothing in sprint N+1 starts until its named sprint-N deps are done.
- Spikes are time-boxed and marked `[SPIKE]`; they produce a decision/doc, not shippable code.
- Track status in your tracker (Jira/Linear); these files are the source backlog and stay in `plans/`.

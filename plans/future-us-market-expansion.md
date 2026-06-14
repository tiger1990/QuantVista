# Future Plan — US Market Expansion (S&P 100)

> **Status:** Deferred (v1 is India / Nifty 200, D2). The v1 core is built **market-agnostic** so this is
> additive — adapters + configuration + data, not a rewrite.

---

## 1. Why it's cheap if v1 is built right

The architecture already isolates market specifics behind abstractions:
- `markets` table + `market_id` on stocks (currency, timezone, trading calendar) — `03`.
- `IMarketDataProvider` / `INewsProvider` adapters — swap/extend per market.
- Cross-sectional scoring normalizes **within a universe**, so a new universe is configuration.

If anything in v1 hard-codes "NSE/INR/IST", fix it now — that's the only real migration cost.

## 2. What US expansion adds

1. **Data adapters:** US vendors (e.g., paid tiers of Financial Modeling Prep / Polygon / Alpha Vantage /
   Finnhub). US market data is generally cleaner and easier to license commercially than India — a plus.
2. **Universe & calendar:** S&P 100 constituents (point-in-time), NYSE/Nasdaq trading calendar, USD.
3. **Fundamentals mapping:** US GAAP fields, ownership data (13F institutional holdings instead of
   promoter/FII/DII), different shareholding semantics — handled via the factor abstraction.
4. **FX & multi-currency:** display and (later) cross-market portfolios; base-currency handling already
   present on `portfolios`.
5. **News/sentiment:** broader English-language coverage; FinBERT works well on US financial news.
6. **Benchmarks:** S&P 100 / S&P 500 TRI for backtests.

## 3. Compliance note

US market coverage as a **research tool** stays under D1's posture. Personalized advice to US persons would
trigger **SEC/State RIA** obligations — that belongs to `future-ria-compliance.md`, not here.

## 4. Sequencing (high level)

Vendor selection (US) → market/calendar/constituents seed → US adapter → factor mapping (GAAP/13F) →
validate scores & backtests on S&P 100 → enable universe selector in UI → launch US coverage tier.

## 5. Watch-outs

- Don't let India-specific factors (promoter/FII/DII) leak into the generic scoring path — keep them as
  market-scoped factors that simply don't apply to US stocks.
- Keep universes isolated for cross-sectional normalization (don't normalize Indian and US stocks together
  unless explicitly building a global universe).

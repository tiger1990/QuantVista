# Sprint 09 — Backtesting II (Parquet, Metrics, Methodology, UI)

**Phase:** 4 · **Goal:** scale backtests via Parquet, complete the metrics suite, publish the methodology
page, and ship the backtest UI.
**Exit gate:** reproducible, bias-controlled backtests usable in product with results vs benchmark.

> See `../03-data-architecture.md` §7, `../05` §4, `../07` §1 (methodology/disclaimer).

---

### QV-067 — Parquet offload + DuckDB/Polars read path `[DATA]` · `8pts` · Epic: EPIC-BT · depends: QV-065
**Story:** As a quant, I want fast multi-year reads, so backtests don't hammer Postgres.
**Acceptance criteria:**
- Historical partitions exported to Parquet on S3/MinIO path-partitioned `/{market}/{table}/{year}/{month}/`;
  backtest engine reads via DuckDB/Polars; measurable speedup vs Postgres scan.
**Notes:** `03` §7.

### QV-068 — Performance & risk metrics suite `[QUANT]` · `5pts` · Epic: EPIC-BT · depends: QV-065
**Story:** As a user, I want standard backtest metrics, so I can judge a strategy.
**Acceptance criteria:**
- CAGR, annualized vol, Sharpe, Sortino, max drawdown, hit rate, turnover, exposure-over-time; benchmark
  comparison; stored in `backtests.metrics` + artifact.
**Notes:** `05` §4.

### QV-069 — Reproducibility guarantee `[QUANT]` · `3pts` · Epic: EPIC-BT · depends: QV-065, QV-068
**Story:** As a user, I want the same spec to yield the same result, so backtests are trustworthy.
**Acceptance criteria:**
- Backtest stores full `spec` + `model_version` + `weights_version`; re-run reproduces metrics; test asserts
  determinism.
**Notes:** `05` §4 point 7.

### QV-070 — Methodology & Disclaimer page `[PROD]` · `3pts` · Epic: EPIC-COMP · depends: QV-011
**Story:** As compliance/product, I want published methodology + assumptions, so the research-tool posture is
explicit and trust is built.
**Acceptance criteria:**
- Page documents scoring methodology, weights, PIT/survivorship controls, backtest cost assumptions, and the
  non-advice disclaimer; linked from backtest/score surfaces.
**Notes:** `07` §1; launch-blocking content finalized in Sprint 11.

### QV-071 — Frontend: Backtest setup + results `[FE]` · `8pts` · Epic: EPIC-BT · depends: QV-062, QV-068, QV-056
**Story:** As a user, I want to configure and review backtests, so I validate strategies visually.
**Acceptance criteria:**
- Setup form (universe, rules, range, costs, benchmark) with tier gating (Free none / Pro limited 1y presets /
  Quant full); async progress; equity curve vs Nifty 200 TRI + metrics table; methodology link + disclaimer.
**Notes:** `01` §4 / Pillar E; `04` §3.6.

**Sprint total:** ~27 pts.

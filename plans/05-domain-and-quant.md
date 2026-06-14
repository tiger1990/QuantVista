# 05 — Domain Design & Quantitative Engine

> Class/domain design for the Analytics and Portfolio modules, the factor & scoring framework, portfolio
> optimization, **backtesting rigor (bias controls)**, and the ML architecture.

---

## 1. Domain model (class design)

The quant core is built around a small, extensible set of abstractions. New factors and optimizers plug in
without touching the engine — Open/Closed by design.

### 1.1 Factor framework
```python
class FactorCategory(Enum):
    FUNDAMENTAL = "fundamental"; MOMENTUM = "momentum"; QUALITY = "quality"
    SENTIMENT = "sentiment"; RISK = "risk"

class Factor(ABC):
    key: str
    category: FactorCategory
    direction: int            # +1 higher-is-better, -1 lower-is-better (e.g., debt/equity)
    @abstractmethod
    def compute(self, ctx: "ScoringContext", stock_id: UUID, as_of: date) -> float | None:
        """Return the RAW factor value using only PIT data; None if unavailable."""

# Concrete examples
class ROEFactor(Factor):        key="roe";  category=QUALITY;      direction=+1
class PEFactor(Factor):         key="pe";   category=FUNDAMENTAL;  direction=-1
class Return6MFactor(Factor):   key="ret_6m"; category=MOMENTUM;   direction=+1
class BetaFactor(Factor):       key="beta"; category=RISK;         direction=-1
class SentimentFactor(Factor):  key="sentiment"; category=SENTIMENT; direction=+1
```

`ScoringContext` provides **PIT repositories** (`fundamentals.as_of(date)`, `prices.window(...)`,
`sentiment.as_of(date)`) and the universe membership at `as_of`. Factors never read "latest" data directly —
this is the structural defense against look-ahead bias.

### 1.2 Normalization & scoring
```python
class Normalizer:
    """Cross-sectional: z-score within sector, winsorized, then mapped to 0–100 percentile."""
    def normalize(self, values: dict[UUID, float], direction: int) -> dict[UUID, float]: ...

class ScoreWeights:               # versioned; default per `12 scoring framework`
    fundamental: float; momentum: float; quality: float; sentiment: float; risk: float
    version: str

class ScoreEngine:
    def __init__(self, factors: list[Factor], normalizer: Normalizer, weights: ScoreWeights): ...
    def compute_universe(self, universe: str, as_of: date) -> list[StockScore]:
        # 1. compute raw factors for all stocks (Polars vectorized)
        # 2. normalize cross-sectionally per category
        # 3. blend category scores via weights -> composite
        # 4. persist scores + factor_values (decomposition) with weights_version/model_version
```

`StockScore` carries sub-scores, composite, and the **decomposition** (factor → contribution) so the API in
`04` can prove the parts sum to the whole.

### 1.3 Portfolio & risk
```python
class Optimizer(ABC):
    @abstractmethod
    def optimize(self, candidates: list[UUID], cov: Matrix, exp_ret: Vector,
                 constraints: Constraints, as_of: date) -> Allocation: ...

class MeanVarianceOptimizer(Optimizer): ...
class RiskParityOptimizer(Optimizer): ...
class BlackLittermanOptimizer(Optimizer): ...   # phase 3
class HRPOptimizer(Optimizer): ...              # phase 4

class RiskEngine:
    def metrics(self, portfolio, as_of) -> RiskMetrics:   # beta, vol, drawdown, Sharpe, Sortino, HHI, sector exposure

class PortfolioService:           # tenant-scoped; orchestrates optimizer + risk + persistence
    def optimize(self, portfolio_id, request) -> OptimizationResult: ...
    def rebalance(self, portfolio_id, drift_threshold) -> list[Trade]: ...
```

### 1.4 News/sentiment
```python
class SentimentModel(ABC):
    def classify(self, text: str) -> SentimentResult: ...   # label, score, confidence
class FinBERTSentiment(SentimentModel): ...
class EventImpactScorer:                                    # maps event type -> impact (e.g., +25 contract win, -40 ban)
    def score(self, news: News, sentiment: SentimentResult) -> float: ...
```

---

## 2. Scoring framework (default weights, v1)

Composite = weighted blend of category scores (each already 0–100, cross-sectionally normalized):

| Category | Composite weight | Representative factors (intra-category weights) |
|----------|------------------|-------------------------------------------------|
| Fundamental | **40%** | PE(15) ROE(20) ROCE(20) D/E(15) RevGrowth(15) EPSGrowth(15) |
| Momentum | **20%** | 3M(30) 6M(30) 12M(40), relative strength, 52w-high distance |
| Quality | **20%** | ROIC, margin stability, cash-flow stability, debt levels |
| Sentiment | **10%** | aggregated news sentiment + event impact (decayed) |
| Risk | **10%** | beta, volatility, max drawdown (direction −1) |

- Weights are **versioned** (`weights_version`) and **user-customizable on Quant tier**.
- Missing-data policy: a factor returning `None` is excluded and the category re-normalized over available
  factors; coverage flag recorded so the UI can show "based on N/M factors."
- Every score persists its `factor_values` so the decomposition is reproducible and auditable.

---

## 3. Portfolio optimization (phased)

| Phase | Method | When | Notes |
|-------|--------|------|-------|
| 1 | **Mean-Variance (Markowitz)** | MVP portfolio feature | `min wᵀΣw` s.t. return target, sector caps, max weight, long-only. Use shrinkage covariance (Ledoit-Wolf) — sample covariance is unstable. |
| 2 | **Risk Parity** | Pro | More robust for retail; equalizes risk contribution. |
| 3 | **Black-Litterman** | Quant | Blends market equilibrium with QuantVista score-derived views. |
| 4 | **Hierarchical Risk Parity (HRP)** | Quant | Clustering-based; no matrix inversion, robust out-of-sample. |

Constraints engine is shared across optimizers (max weight, sector caps, cardinality, turnover limit,
target vol/return). Infeasible problems return the binding constraint, not a silent failure.

---

## 4. Backtesting — correctness is the product (do not cut corners)

A backtest that lies is worse than none. The engine enforces:

1. **No look-ahead bias.** At each rebalance date `D`, signals/scores/fundamentals are read via PIT
   repositories (`knowledge_from <= D`). The engine cannot see data published after `D`.
2. **No survivorship bias.** Universe at `D` = `index_constituents` membership at `D`, including names later
   delisted (`stocks.delisted_on`). Delisting handled as a forced exit at last valid price.
3. **Realistic frictions.** Transaction costs (bps), slippage assumption, and turnover are modeled and
   reported. Rebalance cadence configurable (monthly default).
4. **Corporate-action-adjusted returns** via `adj_close`.
5. **Benchmark = total-return index** (Nifty 200 TRI), not price index — apples to apples.
6. **Metrics:** CAGR, annualized vol, Sharpe, Sortino, max drawdown, hit rate, turnover, exposure over time.
7. **Reproducibility:** a backtest stores its full `spec` + `model_version` + `weights_version`; re-running
   the same spec yields the same result (deterministic seeds for any stochastic step).

**Bias regression tests** (in CI): synthetic fixtures that would only pass if the engine leaked future data
or dropped delisted names — these guard the two cardinal sins permanently.

---

## 5. Machine learning architecture (augments, never replaces, the factor model)

- **Role:** ML provides an *additional* ranking signal and risk/return estimates; the transparent factor
  composite remains the explainable default. ML outputs are clearly labeled and versioned.
- **Features:** the same PIT factor set (100+ engineered features: fundamentals, technicals, ownership,
  sentiment, macro) — reusing `factor_values` guarantees train/serve consistency and no leakage.
- **Models:**
  - Ranking / cross-sectional return: **XGBoost / LightGBM / CatBoost** (learning-to-rank or regression).
  - Risk: **LightGBM** for volatility/drawdown estimation.
  - Forecasting (future phase): Temporal Fusion Transformer — explicitly deferred.
- **Training discipline:** walk-forward / purged time-series CV (no random K-fold on time series), embargo
  around rebalance to prevent leakage. Track experiments + datasets + metrics.
- **Serving:** batch scoring in the nightly pipeline writes ML scores alongside factor scores; `model_version`
  recorded on every row. Model artifacts in object store + registry pointer.
- **Governance:** champion/challenger; a model only promotes if it beats the factor baseline on out-of-sample,
  bias-controlled backtests. Drift monitoring on feature distributions and live performance.

---

## 6. Why this design holds up

- **Extensible:** add a `Factor` or `Optimizer` subclass — engine unchanged (Open/Closed).
- **Explainable:** decomposition persisted; every number traces to PIT inputs.
- **Trustworthy:** bias controls are structural (PIT repos, historical universe) and test-enforced.
- **Performant:** Polars-vectorized cross-sectional math over ~200 symbols is sub-second; heavy backtests run
  async over Parquet.

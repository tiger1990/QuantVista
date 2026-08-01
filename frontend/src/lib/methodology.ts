/**
 * Published methodology facts, mirrored from the backend.
 *
 * The backend is the source of truth: `analytics/scoring.py` (MODEL_VERSION, DEFAULT_WEIGHTS),
 * `analytics/normalizer.py` (winsor bounds), `analytics/backtest.py` (SLIPPAGE_BPS,
 * WEIGHTS_VERSION) and `api/routes_stocks.py` (DISCLAIMER). A published page that quietly drifts
 * from the engine is worse than no page, so `backend/tests/test_methodology_constants.py` fails
 * the build if any value here stops matching its Python counterpart.
 */

/** Methodology fingerprint — bumped on ANY scoring-methodology change. */
export const MODEL_VERSION = "score-v1";

/** Category-weight set used to blend factor scores into the composite. */
export const SCORING_WEIGHTS_VERSION = "v1";

/** Allocation scheme the backtest engine applies to its selections. */
export const BACKTEST_WEIGHTS_VERSION = "equal-weight-v1";

/** Fixed slippage assumption (bps) added to the user's commission on each unit of turnover. */
export const SLIPPAGE_BPS = 5;

/** Upper bound the API accepts for user-supplied costs (bps). */
export const COSTS_BPS_MAX = 500;

/** Raw factor values are winsorized to this sector percentile band before the z-score. */
export const WINSOR_LO_PCT = 1;
export const WINSOR_HI_PCT = 99;

/** The composite's category weights (sum to 1.0). */
export const CATEGORY_WEIGHTS: readonly { category: string; weight: number }[] = [
  { category: "Fundamental", weight: 0.4 },
  { category: "Momentum", weight: 0.2 },
  { category: "Quality", weight: 0.2 },
  { category: "Sentiment", weight: 0.1 },
  { category: "Risk", weight: 0.1 },
];

/** Rebalance cadences a backtest may use. */
export const REBALANCE_CADENCES = ["weekly", "monthly", "quarterly"] as const;

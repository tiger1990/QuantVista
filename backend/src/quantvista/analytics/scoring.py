"""ScoreEngine (QV-029) — cross-sectional composite scoring, score-v1.

Pipeline (``05`` §1.2): raw factors (PIT via QV-028's ``ScoringContext``) → per-factor sector-z →
0–100 percentile (``Normalizer``) → equal-weight **category** sub-scores over *available* factors →
composite = category weights (``05`` §2 defaults) **re-normalized over scored categories** (so
sentiment, which has no factor yet, drops and its weight redistributes). The **decomposition sums to
the composite** exactly. ``model_version`` fingerprints the whole methodology for reproducibility.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from quantvista.analytics.context import ScoringContext
from quantvista.analytics.factors import ALL_FACTORS, Factor, FactorCategory
from quantvista.analytics.normalizer import Normalizer
from quantvista.market_data.repositories import stock_sectors

MODEL_VERSION = "score-v1"  # bump on ANY methodology change (see scoring-methodology-roadmap)


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    fundamental: float
    momentum: float
    quality: float
    sentiment: float
    risk: float
    version: str

    def of(self, category: FactorCategory) -> float:
        return float(getattr(self, category.value))


DEFAULT_WEIGHTS = ScoreWeights(
    fundamental=0.40, momentum=0.20, quality=0.20, sentiment=0.10, risk=0.10, version="v1"
)


@dataclass(frozen=True, slots=True)
class FactorValue:
    factor_key: str
    raw_value: float
    zscore: float
    percentile_sector: float
    percentile_universe: float


@dataclass(frozen=True, slots=True)
class StockScore:
    stock_id: UUID
    date: date
    fundamental: float | None
    momentum: float | None
    quality: float | None
    sentiment: float | None
    risk: float | None
    composite: float
    coverage: float
    weights_version: str
    model_version: str
    factor_values: tuple[FactorValue, ...]
    decomposition: dict[str, float]  # category → contribution; Σ == composite


class ScoreEngine:
    def __init__(
        self,
        factors: Sequence[Factor] = ALL_FACTORS,
        normalizer: Normalizer | None = None,
        weights: ScoreWeights = DEFAULT_WEIGHTS,
    ) -> None:
        self._factors = tuple(factors)
        self._norm = normalizer or Normalizer()
        self._weights = weights

    def compute_universe(
        self, session: Session, universe: Sequence[UUID], as_of: date
    ) -> list[StockScore]:
        """Score every stock in ``universe`` at ``as_of`` (pure — reads only; caller persists)."""
        stocks = list(universe)
        ctx = ScoringContext(session, as_of, stocks)
        sectors = stock_sectors(session, stocks)

        # Per factor: raw for all stocks, then normalize cross-sectionally.
        raw_by_factor: dict[str, dict[UUID, float | None]] = {}
        norm_by_factor = {}
        for factor in self._factors:
            raws = {sid: factor.compute(ctx, sid, as_of) for sid in stocks}
            raw_by_factor[factor.key] = raws
            norm_by_factor[factor.key] = self._norm.normalize(raws, sectors, factor.direction)

        scores: list[StockScore] = []
        for sid in stocks:
            fvs: list[FactorValue] = []
            per_category: dict[FactorCategory, list[float]] = defaultdict(list)
            for factor in self._factors:
                result = norm_by_factor[factor.key].get(sid)
                if result is None:
                    continue  # factor unavailable for this stock — excluded
                raw = raw_by_factor[factor.key][sid]
                assert raw is not None  # present iff normalized
                fvs.append(
                    FactorValue(
                        factor.key,
                        raw,
                        result.zscore,
                        result.percentile_sector,
                        result.percentile_universe,
                    )
                )
                per_category[factor.category].append(result.percentile_universe)

            if not fvs:
                continue  # zero coverage → no meaningful score (skip, don't fabricate a 0)

            sub = {cat: sum(vals) / len(vals) for cat, vals in per_category.items()}
            composite, decomposition = self._blend(sub)
            scores.append(
                StockScore(
                    stock_id=sid,
                    date=as_of,
                    fundamental=sub.get(FactorCategory.FUNDAMENTAL),
                    momentum=sub.get(FactorCategory.MOMENTUM),
                    quality=sub.get(FactorCategory.QUALITY),
                    sentiment=sub.get(FactorCategory.SENTIMENT),
                    risk=sub.get(FactorCategory.RISK),
                    composite=composite,
                    coverage=len(fvs) / len(self._factors) * 100.0,
                    weights_version=self._weights.version,
                    model_version=MODEL_VERSION,
                    factor_values=tuple(fvs),
                    decomposition=decomposition,
                )
            )
        return scores

    def _blend(self, sub: dict[FactorCategory, float]) -> tuple[float, dict[str, float]]:
        """Weighted blend over scored categories, weights re-normalized to sum to 1."""
        weights = {cat: self._weights.of(cat) for cat in sub}
        total = sum(weights.values())
        if total == 0:
            return 0.0, {}
        decomposition = {cat.value: weights[cat] / total * sub[cat] for cat in sub}
        return sum(decomposition.values()), decomposition

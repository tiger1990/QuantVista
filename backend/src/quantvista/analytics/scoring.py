"""Factor + score engines (QV-029 / QV-030) — factors as canonical artifact, scores as projection.

Two responsibilities that evolve independently (``05`` §1.2):
- **FactorEngine** (statistics): raw factors (PIT) → sector-z → 0–100 percentile. The **expensive,
  canonical** ``factor_values`` many consumers reuse (score-v1/v2, ESG, optimizer, ML): normalize
  once, project many.
- **ScoreEngine** (methodology): read a factor snapshot → equal-weight **category** sub-scores over
  available factors → composite = category weights (``05`` §2) **re-normalized over scored
  categories** (sentiment has no factor yet → drops). **Decomposition == composite.**

``compute_universe`` composes both. ``MODEL_VERSION`` fingerprints the methodology (both engines
share it → factors and scores are always the same methodology).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
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


class FactorEngine:
    """Statistics: compute + normalize the canonical ``factor_values`` snapshot for a universe."""

    def __init__(
        self, factors: Sequence[Factor] = ALL_FACTORS, normalizer: Normalizer | None = None
    ):
        self._factors = tuple(factors)
        self._norm = normalizer or Normalizer()

    def compute_factor_values(
        self, session: Session, universe: Sequence[UUID], as_of: date
    ) -> dict[UUID, list[FactorValue]]:
        """Per stock: the normalized factor values (only available factors)."""
        stocks = list(universe)
        ctx = ScoringContext(session, as_of, stocks)
        sectors = stock_sectors(session, stocks)

        by_stock: dict[UUID, list[FactorValue]] = defaultdict(list)
        for factor in self._factors:
            raws = {sid: factor.compute(ctx, sid, as_of) for sid in stocks}
            for sid, result in self._norm.normalize(raws, sectors, factor.direction).items():
                raw = raws[sid]
                assert raw is not None  # present iff normalized
                by_stock[sid].append(
                    FactorValue(
                        factor.key,
                        raw,
                        result.zscore,
                        result.percentile_sector,
                        result.percentile_universe,
                    )
                )
        return dict(by_stock)


class ScoreEngine:
    """Business methodology: project a factor snapshot into per-category + composite scores."""

    def __init__(
        self, factors: Sequence[Factor] = ALL_FACTORS, weights: ScoreWeights = DEFAULT_WEIGHTS
    ):
        self._factors = tuple(factors)
        self._weights = weights
        self._category = {f.key: f.category for f in self._factors}

    def compute_scores(
        self, factor_values: Mapping[UUID, Sequence[FactorValue]], as_of: date
    ) -> list[StockScore]:
        """Blend a factor snapshot into ``StockScore``s (decomposition sums to composite)."""
        total = len(self._factors)
        scores: list[StockScore] = []
        for sid, fvs in factor_values.items():
            if not fvs:
                continue  # zero coverage → no meaningful score
            per_category: dict[FactorCategory, list[float]] = defaultdict(list)
            for fv in fvs:
                per_category[self._category[fv.factor_key]].append(fv.percentile_universe)
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
                    coverage=len(fvs) / total * 100.0,
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


def compute_universe(
    session: Session,
    universe: Sequence[UUID],
    as_of: date,
    *,
    factors: Sequence[Factor] = ALL_FACTORS,
    normalizer: Normalizer | None = None,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> list[StockScore]:
    """Compose the two engines: normalize the factor snapshot, then project it into scores."""
    snapshot = FactorEngine(factors, normalizer).compute_factor_values(session, universe, as_of)
    return ScoreEngine(factors, weights).compute_scores(snapshot, as_of)

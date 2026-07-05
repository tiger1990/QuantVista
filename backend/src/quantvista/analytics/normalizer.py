"""Cross-sectional normalizer (QV-029) — sector z-score → percentile, direction-adjusted.

Per factor, across the universe (Polars-vectorized): direction-adjust the raw (``× direction`` so
higher = better) → **winsorize the raw to the sector's [p1, p99]** (before z — a few extreme filings
would distort mean/std) → **sector z-score** (sample std; σ=0 / singleton → neutral 0) → rank to
0–100 ``percentile_sector`` (within sector) + ``percentile_universe`` (of the sector-z, across all).
None / non-finite inputs are excluded (basic factor-quality guard). ``05`` §1.2.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

import polars as pl

_WINSOR_LO, _WINSOR_HI = 0.01, 0.99
_NONE_SECTOR = "__none__"


@dataclass(frozen=True, slots=True)
class NormResult:
    zscore: float
    percentile_sector: float
    percentile_universe: float


def _percent_rank(col: pl.Expr) -> pl.Expr:
    # (rank-1)/(n-1)*100 over the group; a singleton (n==1) → neutral 50.
    n = col.count()
    rank = col.rank(method="average")
    return pl.when(n > 1).then((rank - 1) / (n - 1) * 100.0).otherwise(50.0)


class Normalizer:
    """Sector-relative normalization to 0–100, higher = better."""

    def normalize(
        self,
        values: Mapping[UUID, float | None],
        sectors: Mapping[UUID, str | None],
        direction: int,
    ) -> dict[UUID, NormResult]:
        rows = [
            {"stock_id": str(sid), "sector": sectors.get(sid) or _NONE_SECTOR, "raw": float(v)}
            for sid, v in values.items()
            if v is not None and math.isfinite(v)
        ]
        if not rows:
            return {}

        df = pl.DataFrame(rows).with_columns((pl.col("raw") * direction).alias("adj"))
        # Winsorize the direction-adjusted raw to the sector's [p1, p99] before computing moments.
        df = df.with_columns(
            pl.col("adj")
            .clip(
                pl.col("adj").quantile(_WINSOR_LO).over("sector"),
                pl.col("adj").quantile(_WINSOR_HI).over("sector"),
            )
            .alias("w")
        )
        mean = pl.col("w").mean().over("sector")
        std = pl.col("w").std().over("sector")  # sample std (ddof=1)
        df = df.with_columns(
            pl.when((std.is_not_null()) & (std > 0))
            .then((pl.col("w") - mean) / std)
            .otherwise(0.0)
            .alias("z")
        )
        df = df.with_columns(
            _percent_rank(pl.col("w")).over("sector").alias("pct_sector"),
            _percent_rank(pl.col("z")).alias("pct_universe"),
        )

        return {
            UUID(r["stock_id"]): NormResult(
                zscore=float(r["z"]),
                percentile_sector=float(r["pct_sector"]),
                percentile_universe=float(r["pct_universe"]),
            )
            for r in df.to_dicts()
        }

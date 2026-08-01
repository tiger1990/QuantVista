"""PIT feature store built on ``factor_values`` (QV-087).

`factor_values` is already point-in-time: the row for date ``D`` was computed from data knowable at
``D`` (QV-029 over the QV-063/064 PIT seams). Reading rows with ``date <= T`` therefore cannot leak.

**The leakage risk lives entirely in the engineering here**, so every derived column is built from
`shift`/trailing-window expressions partitioned by stock and ordered by date. There is no centred
window, no forward fill, and no cross-sectional statistic computed over the whole panel — a
`mean()` taken across dates would quietly mix the future into the past.

Train and serve share one code path (`build_features`): the training panel is that function over a
range, and a serving row is the same function for a single date. They cannot drift, which is the
point — `05` §5 asks for features "identical to serving features", and a promise in a docstring is
not a guarantee.

Output is an in-memory Polars frame. Persisting training sets is QV-088's decision, once the
trainer's access pattern is known.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import polars as pl

#: The stored representations of every factor. Each becomes a base feature column.
REPRESENTATIONS: tuple[str, ...] = (
    "raw_value",
    "zscore",
    "percentile_sector",
    "percentile_universe",
)

#: Trailing windows (in trading sessions) for the time-series features. ~1 and ~3 months.
LAG_WINDOWS: tuple[int, ...] = (21, 63)
ROLL_WINDOWS: tuple[int, ...] = (21, 63)

#: Identity columns carried through the pipeline but never fed to a model as features.
ID_COLUMNS: tuple[str, ...] = ("stock_id", "date")


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """One engineered column: what it is, where it came from, and how it was derived.

    This is the machine-readable feature catalog. `docs/feature-catalog.md` is generated from it,
    and a test fails if they disagree — a catalog maintained by hand rots within two stories.
    """

    name: str
    family: str  # base | lag | delta | rolling_mean | rolling_std
    source_factor: str
    representation: str
    window: int | None
    description: str


def _base_name(factor: str, rep: str) -> str:
    return f"{factor}__{rep}"


def feature_specs(factor_keys: Sequence[str]) -> list[FeatureSpec]:
    """Every feature the pipeline produces, for a given factor set — the catalog's source.

    Derived features are built on ``zscore`` only: it is the sector-relative, winsorized
    representation (QV-029), so a change in it means a change in standing rather than a change in
    units. Differencing raw P/E across time would mix level and scale effects.
    """
    specs: list[FeatureSpec] = []
    for factor in factor_keys:
        for rep in REPRESENTATIONS:
            specs.append(
                FeatureSpec(
                    name=_base_name(factor, rep),
                    family="base",
                    source_factor=factor,
                    representation=rep,
                    window=None,
                    description=f"{rep} of {factor} as published for that date",
                )
            )
    for factor in factor_keys:
        base = _base_name(factor, "zscore")
        for w in LAG_WINDOWS:
            specs.append(
                FeatureSpec(
                    name=f"{base}__lag{w}",
                    family="lag",
                    source_factor=factor,
                    representation="zscore",
                    window=w,
                    description=f"{factor} z-score as it stood {w} sessions earlier",
                )
            )
            specs.append(
                FeatureSpec(
                    name=f"{base}__delta{w}",
                    family="delta",
                    source_factor=factor,
                    representation="zscore",
                    window=w,
                    description=f"change in {factor} z-score over the trailing {w} sessions",
                )
            )
        for w in ROLL_WINDOWS:
            specs.append(
                FeatureSpec(
                    name=f"{base}__rollmean{w}",
                    family="rolling_mean",
                    source_factor=factor,
                    representation="zscore",
                    window=w,
                    description=f"mean {factor} z-score over the trailing {w} sessions (inclusive)",
                )
            )
            specs.append(
                FeatureSpec(
                    name=f"{base}__rollstd{w}",
                    family="rolling_std",
                    source_factor=factor,
                    representation="zscore",
                    window=w,
                    description=(
                        f"stability of {factor}: std of its z-score over the trailing {w} sessions"
                    ),
                )
            )
    return specs


def feature_names(factor_keys: Sequence[str]) -> list[str]:
    return [s.name for s in feature_specs(factor_keys)]


def _pivot_long_panel(rows: Sequence[dict[str, object]]) -> pl.DataFrame:
    """Long ``(stock, date, factor, representations…)`` → wide one-row-per ``(stock, date)``.

    ``stock_id`` is normalised to text: the repository hands back `UUID` objects, which Polars
    cannot hold in a typed column, while tests and callers may pass strings. Coercing here keeps
    both paths on one schema — the alternative is a frame whose dtype depends on its caller.
    """
    normalised = [{**row, "stock_id": str(row["stock_id"])} for row in rows]
    long = pl.DataFrame(
        normalised,
        schema={
            "stock_id": pl.String,
            "date": pl.Date,
            "factor_key": pl.String,
            "raw_value": pl.Float64,
            "zscore": pl.Float64,
            "percentile_sector": pl.Float64,
            "percentile_universe": pl.Float64,
        },
        strict=False,
    )
    wide = long.pivot(
        on="factor_key", index=["stock_id", "date"], values=list(REPRESENTATIONS), separator="__"
    )
    # polars names pivoted columns `<representation>__<factor>`; the catalog uses `<factor>__<rep>`
    renames = {
        f"{rep}__{factor}": _base_name(factor, rep)
        for rep in REPRESENTATIONS
        for factor in long["factor_key"].unique()
        if f"{rep}__{factor}" in wide.columns
    }
    return wide.rename(renames)


def build_features(
    rows: Sequence[dict[str, object]], factor_keys: Sequence[str], *, as_of: date | None = None
) -> pl.DataFrame:
    """The one feature path, used for both training panels and single-date serving.

    ``rows`` is the long panel from ``analytics.repositories.factor_values_panel``. Pass ``as_of``
    to get the single row per stock for that date — computed from the *same* trailing history, so a
    served row is bit-identical to that date's row in a training panel.

    Every derived column is trailing-only: ``shift(w)`` and ``rolling_*`` over a window ending at
    the current row, partitioned ``over("stock_id")`` and ordered by date.
    """
    if not rows:
        return pl.DataFrame()

    wide = _pivot_long_panel(rows).sort(["stock_id", "date"])

    exprs: list[pl.Expr] = []
    for factor in factor_keys:
        base = _base_name(factor, "zscore")
        if base not in wide.columns:
            continue  # a factor absent from this panel yields no derived columns for it
        col = pl.col(base)
        for w in LAG_WINDOWS:
            exprs.append(col.shift(w).over("stock_id").alias(f"{base}__lag{w}"))
            exprs.append((col - col.shift(w)).over("stock_id").alias(f"{base}__delta{w}"))
        for w in ROLL_WINDOWS:
            exprs.append(
                col.rolling_mean(window_size=w, min_samples=1)
                .over("stock_id")
                .alias(f"{base}__rollmean{w}")
            )
            exprs.append(
                col.rolling_std(window_size=w, min_samples=2)
                .over("stock_id")
                .alias(f"{base}__rollstd{w}")
            )

    out = wide.with_columns(exprs) if exprs else wide

    # Column order follows the catalog, so a frame is self-describing and diffable.
    ordered = [*ID_COLUMNS, *[n for n in feature_names(factor_keys) if n in out.columns]]
    out = out.select(ordered)

    if as_of is not None:
        out = out.filter(pl.col("date") == as_of)
    return out


def serve_features(
    rows: Sequence[dict[str, object]], factor_keys: Sequence[str], *, as_of: date
) -> pl.DataFrame:
    """The serving view: one row per stock for ``as_of``.

    A thin alias over ``build_features`` **on purpose** — if serving had its own implementation,
    train/serve skew would be a matter of discipline instead of construction. Callers must still
    pass history before ``as_of`` so trailing windows are populated.
    """
    return build_features(rows, factor_keys, as_of=as_of)


def stock_ids_of(frame: pl.DataFrame) -> list[UUID]:
    return [UUID(str(v)) for v in frame["stock_id"].to_list()]


__all__ = [
    "ID_COLUMNS",
    "LAG_WINDOWS",
    "REPRESENTATIONS",
    "ROLL_WINDOWS",
    "FeatureSpec",
    "build_features",
    "feature_names",
    "feature_specs",
    "serve_features",
    "stock_ids_of",
]

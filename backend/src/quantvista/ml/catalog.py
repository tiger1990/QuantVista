"""Feature-catalog rendering (QV-087).

The catalog is **generated from `feature_specs`**, never hand-maintained. A documented feature list
that someone updates by hand is wrong within two stories, and a wrong catalog is worse than none —
it is the artifact a reviewer trusts when deciding whether a model's inputs are legitimate.

`tests/test_feature_catalog.py` fails when `docs/feature-catalog.md` drifts from the code, and
`scripts/render_feature_catalog.py` regenerates it. Same pattern as the QV-011 terminology guide.
"""

from __future__ import annotations

from collections.abc import Sequence

from quantvista.ml.features import (
    LAG_WINDOWS,
    REPRESENTATIONS,
    ROLL_WINDOWS,
    FeatureSpec,
    feature_specs,
)

_HEADER = """# Feature catalog

> **Generated — do not edit by hand.** Produced from `quantvista.ml.features.feature_specs`;
> regenerate with `python scripts/render_feature_catalog.py`. A test fails if this file drifts
> from the code, because a stale catalog is the artifact a reviewer trusts when judging whether a
> model's inputs are legitimate.

Features are built on `factor_values`, which is point-in-time by construction: the row for date `D`
was computed only from data knowable at `D`. **Every derived column here is trailing-only** —
`shift(w)` and rolling windows ending at the current row, partitioned by stock and ordered by date.
There is no centred window, no forward fill, and no statistic computed across dates, any of which
would mix the future into the past.

Training and serving use the **same function** (`build_features`); the serving view is that
function for a single date. They cannot drift.
"""


def _families_section() -> str:
    lags = ", ".join(map(str, LAG_WINDOWS))
    rolls = ", ".join(map(str, ROLL_WINDOWS))
    reps = "`, `".join(REPRESENTATIONS)
    rows = "".join(
        [
            f"| `base` | all {len(REPRESENTATIONS)} stored representations | — "
            "| the factor as published for that date |\n",
            f"| `lag` | `zscore` | {lags} sessions | where the name stood previously |\n",
            f"| `delta` | `zscore` | {lags} sessions | change in standing over the window |\n",
            f"| `rolling_mean` | `zscore` | {rolls} sessions | the level, smoothed |\n",
            f"| `rolling_std` | `zscore` | {rolls} sessions | stability of the signal |\n",
        ]
    )
    return f"""
## Families

| Family | Built from | Windows | What it captures |
|---|---|---|---|
{rows}
Derived families use **`zscore` only**: it is sector-relative and winsorized (QV-029), so a change
in it means a change in *standing*. Differencing a raw ratio such as P/E across time would conflate
level, scale and sector drift.

The four stored representations are `{reps}`.
"""


def render_catalog(factor_keys: Sequence[str]) -> str:
    """The full catalog markdown for a factor set."""
    specs = feature_specs(factor_keys)
    by_family: dict[str, list[FeatureSpec]] = {}
    for spec in specs:
        by_family.setdefault(spec.family, []).append(spec)

    parts = [
        _HEADER,
        _families_section(),
        f"\n## Summary\n\n**{len(specs)} features** from **{len(factor_keys)}** factors.\n\n"
        "| Family | Count |\n|---|---|\n"
        + "".join(f"| `{fam}` | {len(rows)} |\n" for fam, rows in by_family.items()),
        "\n## Every feature\n\n"
        "| Feature | Family | Factor | Representation | Window | Description |\n"
        "|---|---|---|---|---|---|\n",
    ]
    for spec in specs:
        window = str(spec.window) if spec.window is not None else "—"
        parts.append(
            f"| `{spec.name}` | {spec.family} | {spec.source_factor} | {spec.representation} "
            f"| {window} | {spec.description} |\n"
        )
    parts.append(
        "\n## Not in scope here\n\n"
        "- **Labels, CV splits and embargo** are QV-088. This story produces inputs only.\n"
        "- **Persistence.** Features are returned as an in-memory frame; how training sets are "
        "stored is QV-088's decision, once the trainer's access pattern is known.\n"
        "- **Missing values are left missing.** A stock with no sentiment coverage must not look "
        "like a stock with neutral sentiment, so nothing is zero-filled.\n"
    )
    return "".join(parts)


__all__ = ["render_catalog"]

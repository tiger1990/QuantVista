# Feature catalog

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

## Families

| Family | Built from | Windows | What it captures |
|---|---|---|---|
| `base` | all 4 stored representations | — | the factor as published for that date |
| `lag` | `zscore` | 21, 63 sessions | where the name stood previously |
| `delta` | `zscore` | 21, 63 sessions | change in standing over the window |
| `rolling_mean` | `zscore` | 21, 63 sessions | the level, smoothed |
| `rolling_std` | `zscore` | 21, 63 sessions | stability of the signal |

Derived families use **`zscore` only**: it is sector-relative and winsorized (QV-029), so a change
in it means a change in *standing*. Differencing a raw ratio such as P/E across time would conflate
level, scale and sector drift.

The four stored representations are `raw_value`, `zscore`, `percentile_sector`, `percentile_universe`.

## Summary

**132 features** from **11** factors.

| Family | Count |
|---|---|
| `base` | 44 |
| `lag` | 22 |
| `delta` | 22 |
| `rolling_mean` | 22 |
| `rolling_std` | 22 |

## Every feature

| Feature | Family | Factor | Representation | Window | Description |
|---|---|---|---|---|---|
| `pe__raw_value` | base | pe | raw_value | — | raw_value of pe as published for that date |
| `pe__zscore` | base | pe | zscore | — | zscore of pe as published for that date |
| `pe__percentile_sector` | base | pe | percentile_sector | — | percentile_sector of pe as published for that date |
| `pe__percentile_universe` | base | pe | percentile_universe | — | percentile_universe of pe as published for that date |
| `pb__raw_value` | base | pb | raw_value | — | raw_value of pb as published for that date |
| `pb__zscore` | base | pb | zscore | — | zscore of pb as published for that date |
| `pb__percentile_sector` | base | pb | percentile_sector | — | percentile_sector of pb as published for that date |
| `pb__percentile_universe` | base | pb | percentile_universe | — | percentile_universe of pb as published for that date |
| `roe__raw_value` | base | roe | raw_value | — | raw_value of roe as published for that date |
| `roe__zscore` | base | roe | zscore | — | zscore of roe as published for that date |
| `roe__percentile_sector` | base | roe | percentile_sector | — | percentile_sector of roe as published for that date |
| `roe__percentile_universe` | base | roe | percentile_universe | — | percentile_universe of roe as published for that date |
| `roce__raw_value` | base | roce | raw_value | — | raw_value of roce as published for that date |
| `roce__zscore` | base | roce | zscore | — | zscore of roce as published for that date |
| `roce__percentile_sector` | base | roce | percentile_sector | — | percentile_sector of roce as published for that date |
| `roce__percentile_universe` | base | roce | percentile_universe | — | percentile_universe of roce as published for that date |
| `debt_equity__raw_value` | base | debt_equity | raw_value | — | raw_value of debt_equity as published for that date |
| `debt_equity__zscore` | base | debt_equity | zscore | — | zscore of debt_equity as published for that date |
| `debt_equity__percentile_sector` | base | debt_equity | percentile_sector | — | percentile_sector of debt_equity as published for that date |
| `debt_equity__percentile_universe` | base | debt_equity | percentile_universe | — | percentile_universe of debt_equity as published for that date |
| `ret_3m__raw_value` | base | ret_3m | raw_value | — | raw_value of ret_3m as published for that date |
| `ret_3m__zscore` | base | ret_3m | zscore | — | zscore of ret_3m as published for that date |
| `ret_3m__percentile_sector` | base | ret_3m | percentile_sector | — | percentile_sector of ret_3m as published for that date |
| `ret_3m__percentile_universe` | base | ret_3m | percentile_universe | — | percentile_universe of ret_3m as published for that date |
| `ret_6m__raw_value` | base | ret_6m | raw_value | — | raw_value of ret_6m as published for that date |
| `ret_6m__zscore` | base | ret_6m | zscore | — | zscore of ret_6m as published for that date |
| `ret_6m__percentile_sector` | base | ret_6m | percentile_sector | — | percentile_sector of ret_6m as published for that date |
| `ret_6m__percentile_universe` | base | ret_6m | percentile_universe | — | percentile_universe of ret_6m as published for that date |
| `ret_12m__raw_value` | base | ret_12m | raw_value | — | raw_value of ret_12m as published for that date |
| `ret_12m__zscore` | base | ret_12m | zscore | — | zscore of ret_12m as published for that date |
| `ret_12m__percentile_sector` | base | ret_12m | percentile_sector | — | percentile_sector of ret_12m as published for that date |
| `ret_12m__percentile_universe` | base | ret_12m | percentile_universe | — | percentile_universe of ret_12m as published for that date |
| `beta__raw_value` | base | beta | raw_value | — | raw_value of beta as published for that date |
| `beta__zscore` | base | beta | zscore | — | zscore of beta as published for that date |
| `beta__percentile_sector` | base | beta | percentile_sector | — | percentile_sector of beta as published for that date |
| `beta__percentile_universe` | base | beta | percentile_universe | — | percentile_universe of beta as published for that date |
| `vol_30d__raw_value` | base | vol_30d | raw_value | — | raw_value of vol_30d as published for that date |
| `vol_30d__zscore` | base | vol_30d | zscore | — | zscore of vol_30d as published for that date |
| `vol_30d__percentile_sector` | base | vol_30d | percentile_sector | — | percentile_sector of vol_30d as published for that date |
| `vol_30d__percentile_universe` | base | vol_30d | percentile_universe | — | percentile_universe of vol_30d as published for that date |
| `sentiment__raw_value` | base | sentiment | raw_value | — | raw_value of sentiment as published for that date |
| `sentiment__zscore` | base | sentiment | zscore | — | zscore of sentiment as published for that date |
| `sentiment__percentile_sector` | base | sentiment | percentile_sector | — | percentile_sector of sentiment as published for that date |
| `sentiment__percentile_universe` | base | sentiment | percentile_universe | — | percentile_universe of sentiment as published for that date |
| `pe__zscore__lag21` | lag | pe | zscore | 21 | pe z-score as it stood 21 sessions earlier |
| `pe__zscore__delta21` | delta | pe | zscore | 21 | change in pe z-score over the trailing 21 sessions |
| `pe__zscore__lag63` | lag | pe | zscore | 63 | pe z-score as it stood 63 sessions earlier |
| `pe__zscore__delta63` | delta | pe | zscore | 63 | change in pe z-score over the trailing 63 sessions |
| `pe__zscore__rollmean21` | rolling_mean | pe | zscore | 21 | mean pe z-score over the trailing 21 sessions (inclusive) |
| `pe__zscore__rollstd21` | rolling_std | pe | zscore | 21 | stability of pe: std of its z-score over the trailing 21 sessions |
| `pe__zscore__rollmean63` | rolling_mean | pe | zscore | 63 | mean pe z-score over the trailing 63 sessions (inclusive) |
| `pe__zscore__rollstd63` | rolling_std | pe | zscore | 63 | stability of pe: std of its z-score over the trailing 63 sessions |
| `pb__zscore__lag21` | lag | pb | zscore | 21 | pb z-score as it stood 21 sessions earlier |
| `pb__zscore__delta21` | delta | pb | zscore | 21 | change in pb z-score over the trailing 21 sessions |
| `pb__zscore__lag63` | lag | pb | zscore | 63 | pb z-score as it stood 63 sessions earlier |
| `pb__zscore__delta63` | delta | pb | zscore | 63 | change in pb z-score over the trailing 63 sessions |
| `pb__zscore__rollmean21` | rolling_mean | pb | zscore | 21 | mean pb z-score over the trailing 21 sessions (inclusive) |
| `pb__zscore__rollstd21` | rolling_std | pb | zscore | 21 | stability of pb: std of its z-score over the trailing 21 sessions |
| `pb__zscore__rollmean63` | rolling_mean | pb | zscore | 63 | mean pb z-score over the trailing 63 sessions (inclusive) |
| `pb__zscore__rollstd63` | rolling_std | pb | zscore | 63 | stability of pb: std of its z-score over the trailing 63 sessions |
| `roe__zscore__lag21` | lag | roe | zscore | 21 | roe z-score as it stood 21 sessions earlier |
| `roe__zscore__delta21` | delta | roe | zscore | 21 | change in roe z-score over the trailing 21 sessions |
| `roe__zscore__lag63` | lag | roe | zscore | 63 | roe z-score as it stood 63 sessions earlier |
| `roe__zscore__delta63` | delta | roe | zscore | 63 | change in roe z-score over the trailing 63 sessions |
| `roe__zscore__rollmean21` | rolling_mean | roe | zscore | 21 | mean roe z-score over the trailing 21 sessions (inclusive) |
| `roe__zscore__rollstd21` | rolling_std | roe | zscore | 21 | stability of roe: std of its z-score over the trailing 21 sessions |
| `roe__zscore__rollmean63` | rolling_mean | roe | zscore | 63 | mean roe z-score over the trailing 63 sessions (inclusive) |
| `roe__zscore__rollstd63` | rolling_std | roe | zscore | 63 | stability of roe: std of its z-score over the trailing 63 sessions |
| `roce__zscore__lag21` | lag | roce | zscore | 21 | roce z-score as it stood 21 sessions earlier |
| `roce__zscore__delta21` | delta | roce | zscore | 21 | change in roce z-score over the trailing 21 sessions |
| `roce__zscore__lag63` | lag | roce | zscore | 63 | roce z-score as it stood 63 sessions earlier |
| `roce__zscore__delta63` | delta | roce | zscore | 63 | change in roce z-score over the trailing 63 sessions |
| `roce__zscore__rollmean21` | rolling_mean | roce | zscore | 21 | mean roce z-score over the trailing 21 sessions (inclusive) |
| `roce__zscore__rollstd21` | rolling_std | roce | zscore | 21 | stability of roce: std of its z-score over the trailing 21 sessions |
| `roce__zscore__rollmean63` | rolling_mean | roce | zscore | 63 | mean roce z-score over the trailing 63 sessions (inclusive) |
| `roce__zscore__rollstd63` | rolling_std | roce | zscore | 63 | stability of roce: std of its z-score over the trailing 63 sessions |
| `debt_equity__zscore__lag21` | lag | debt_equity | zscore | 21 | debt_equity z-score as it stood 21 sessions earlier |
| `debt_equity__zscore__delta21` | delta | debt_equity | zscore | 21 | change in debt_equity z-score over the trailing 21 sessions |
| `debt_equity__zscore__lag63` | lag | debt_equity | zscore | 63 | debt_equity z-score as it stood 63 sessions earlier |
| `debt_equity__zscore__delta63` | delta | debt_equity | zscore | 63 | change in debt_equity z-score over the trailing 63 sessions |
| `debt_equity__zscore__rollmean21` | rolling_mean | debt_equity | zscore | 21 | mean debt_equity z-score over the trailing 21 sessions (inclusive) |
| `debt_equity__zscore__rollstd21` | rolling_std | debt_equity | zscore | 21 | stability of debt_equity: std of its z-score over the trailing 21 sessions |
| `debt_equity__zscore__rollmean63` | rolling_mean | debt_equity | zscore | 63 | mean debt_equity z-score over the trailing 63 sessions (inclusive) |
| `debt_equity__zscore__rollstd63` | rolling_std | debt_equity | zscore | 63 | stability of debt_equity: std of its z-score over the trailing 63 sessions |
| `ret_3m__zscore__lag21` | lag | ret_3m | zscore | 21 | ret_3m z-score as it stood 21 sessions earlier |
| `ret_3m__zscore__delta21` | delta | ret_3m | zscore | 21 | change in ret_3m z-score over the trailing 21 sessions |
| `ret_3m__zscore__lag63` | lag | ret_3m | zscore | 63 | ret_3m z-score as it stood 63 sessions earlier |
| `ret_3m__zscore__delta63` | delta | ret_3m | zscore | 63 | change in ret_3m z-score over the trailing 63 sessions |
| `ret_3m__zscore__rollmean21` | rolling_mean | ret_3m | zscore | 21 | mean ret_3m z-score over the trailing 21 sessions (inclusive) |
| `ret_3m__zscore__rollstd21` | rolling_std | ret_3m | zscore | 21 | stability of ret_3m: std of its z-score over the trailing 21 sessions |
| `ret_3m__zscore__rollmean63` | rolling_mean | ret_3m | zscore | 63 | mean ret_3m z-score over the trailing 63 sessions (inclusive) |
| `ret_3m__zscore__rollstd63` | rolling_std | ret_3m | zscore | 63 | stability of ret_3m: std of its z-score over the trailing 63 sessions |
| `ret_6m__zscore__lag21` | lag | ret_6m | zscore | 21 | ret_6m z-score as it stood 21 sessions earlier |
| `ret_6m__zscore__delta21` | delta | ret_6m | zscore | 21 | change in ret_6m z-score over the trailing 21 sessions |
| `ret_6m__zscore__lag63` | lag | ret_6m | zscore | 63 | ret_6m z-score as it stood 63 sessions earlier |
| `ret_6m__zscore__delta63` | delta | ret_6m | zscore | 63 | change in ret_6m z-score over the trailing 63 sessions |
| `ret_6m__zscore__rollmean21` | rolling_mean | ret_6m | zscore | 21 | mean ret_6m z-score over the trailing 21 sessions (inclusive) |
| `ret_6m__zscore__rollstd21` | rolling_std | ret_6m | zscore | 21 | stability of ret_6m: std of its z-score over the trailing 21 sessions |
| `ret_6m__zscore__rollmean63` | rolling_mean | ret_6m | zscore | 63 | mean ret_6m z-score over the trailing 63 sessions (inclusive) |
| `ret_6m__zscore__rollstd63` | rolling_std | ret_6m | zscore | 63 | stability of ret_6m: std of its z-score over the trailing 63 sessions |
| `ret_12m__zscore__lag21` | lag | ret_12m | zscore | 21 | ret_12m z-score as it stood 21 sessions earlier |
| `ret_12m__zscore__delta21` | delta | ret_12m | zscore | 21 | change in ret_12m z-score over the trailing 21 sessions |
| `ret_12m__zscore__lag63` | lag | ret_12m | zscore | 63 | ret_12m z-score as it stood 63 sessions earlier |
| `ret_12m__zscore__delta63` | delta | ret_12m | zscore | 63 | change in ret_12m z-score over the trailing 63 sessions |
| `ret_12m__zscore__rollmean21` | rolling_mean | ret_12m | zscore | 21 | mean ret_12m z-score over the trailing 21 sessions (inclusive) |
| `ret_12m__zscore__rollstd21` | rolling_std | ret_12m | zscore | 21 | stability of ret_12m: std of its z-score over the trailing 21 sessions |
| `ret_12m__zscore__rollmean63` | rolling_mean | ret_12m | zscore | 63 | mean ret_12m z-score over the trailing 63 sessions (inclusive) |
| `ret_12m__zscore__rollstd63` | rolling_std | ret_12m | zscore | 63 | stability of ret_12m: std of its z-score over the trailing 63 sessions |
| `beta__zscore__lag21` | lag | beta | zscore | 21 | beta z-score as it stood 21 sessions earlier |
| `beta__zscore__delta21` | delta | beta | zscore | 21 | change in beta z-score over the trailing 21 sessions |
| `beta__zscore__lag63` | lag | beta | zscore | 63 | beta z-score as it stood 63 sessions earlier |
| `beta__zscore__delta63` | delta | beta | zscore | 63 | change in beta z-score over the trailing 63 sessions |
| `beta__zscore__rollmean21` | rolling_mean | beta | zscore | 21 | mean beta z-score over the trailing 21 sessions (inclusive) |
| `beta__zscore__rollstd21` | rolling_std | beta | zscore | 21 | stability of beta: std of its z-score over the trailing 21 sessions |
| `beta__zscore__rollmean63` | rolling_mean | beta | zscore | 63 | mean beta z-score over the trailing 63 sessions (inclusive) |
| `beta__zscore__rollstd63` | rolling_std | beta | zscore | 63 | stability of beta: std of its z-score over the trailing 63 sessions |
| `vol_30d__zscore__lag21` | lag | vol_30d | zscore | 21 | vol_30d z-score as it stood 21 sessions earlier |
| `vol_30d__zscore__delta21` | delta | vol_30d | zscore | 21 | change in vol_30d z-score over the trailing 21 sessions |
| `vol_30d__zscore__lag63` | lag | vol_30d | zscore | 63 | vol_30d z-score as it stood 63 sessions earlier |
| `vol_30d__zscore__delta63` | delta | vol_30d | zscore | 63 | change in vol_30d z-score over the trailing 63 sessions |
| `vol_30d__zscore__rollmean21` | rolling_mean | vol_30d | zscore | 21 | mean vol_30d z-score over the trailing 21 sessions (inclusive) |
| `vol_30d__zscore__rollstd21` | rolling_std | vol_30d | zscore | 21 | stability of vol_30d: std of its z-score over the trailing 21 sessions |
| `vol_30d__zscore__rollmean63` | rolling_mean | vol_30d | zscore | 63 | mean vol_30d z-score over the trailing 63 sessions (inclusive) |
| `vol_30d__zscore__rollstd63` | rolling_std | vol_30d | zscore | 63 | stability of vol_30d: std of its z-score over the trailing 63 sessions |
| `sentiment__zscore__lag21` | lag | sentiment | zscore | 21 | sentiment z-score as it stood 21 sessions earlier |
| `sentiment__zscore__delta21` | delta | sentiment | zscore | 21 | change in sentiment z-score over the trailing 21 sessions |
| `sentiment__zscore__lag63` | lag | sentiment | zscore | 63 | sentiment z-score as it stood 63 sessions earlier |
| `sentiment__zscore__delta63` | delta | sentiment | zscore | 63 | change in sentiment z-score over the trailing 63 sessions |
| `sentiment__zscore__rollmean21` | rolling_mean | sentiment | zscore | 21 | mean sentiment z-score over the trailing 21 sessions (inclusive) |
| `sentiment__zscore__rollstd21` | rolling_std | sentiment | zscore | 21 | stability of sentiment: std of its z-score over the trailing 21 sessions |
| `sentiment__zscore__rollmean63` | rolling_mean | sentiment | zscore | 63 | mean sentiment z-score over the trailing 63 sessions (inclusive) |
| `sentiment__zscore__rollstd63` | rolling_std | sentiment | zscore | 63 | stability of sentiment: std of its z-score over the trailing 63 sessions |

## Not in scope here

- **Labels, CV splits and embargo** are QV-088. This story produces inputs only.
- **Persistence.** Features are returned as an in-memory frame; how training sets are stored is QV-088's decision, once the trainer's access pattern is known.
- **Missing values are left missing.** A stock with no sentiment coverage must not look like a stock with neutral sentiment, so nothing is zero-filled.

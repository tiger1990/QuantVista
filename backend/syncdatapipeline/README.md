# syncdatapipeline

Dev-only runners that drive the **whole** data pipeline in one process. Not part of the shipped
`quantvista` package and never used in production.

| Script | What it does |
|---|---|
| `resync_all.py` | Re-syncs every pipeline (partitions → universe → prices → … → alerts) in dependency order |

`scripts/dev_backfill.py` remains the narrow tool: prices → indicators → factors → scores. Reach for
`resync_all.py` when the dev database is new or has drifted across *several* datasets.

## Usage

From `backend/` with the venv active:

```bash
python syncdatapipeline/resync_all.py --list                 # print the plan, run nothing
python syncdatapipeline/resync_all.py                        # everything, 400 days
python syncdatapipeline/resync_all.py --days 90 --tolerant   # shorter window, per-stock price isolation
python syncdatapipeline/resync_all.py --only prices,indicators,factors_scores
python syncdatapipeline/resync_all.py --from indicators      # resume a run that died mid-way
python syncdatapipeline/resync_all.py --skip news --continue-on-error
```

`python -m syncdatapipeline.resync_all` works identically.

## Stages

Run in this order, which is the real DAG — not alphabetical:

| # | Stage | Notes |
|---|---|---|
| 1 | `partitions` | Must precede every write, or new-month rows land in `_default` (QV-104) |
| 2 | `universe` | Loads the bundled Nifty 200 CSV, **not** the 5-symbol dev provider list |
| 3 | `prices` | STRICT by default; `--tolerant` isolates per-stock failures (QV-092) |
| 4 | `validate` | Data-quality gate over the whole window |
| 5 | `corpactions` | Recomputes `adj_close` — must precede `indicators` |
| 6 | `fundamentals` | Bitemporal filings; reach scoring on the run *after* ingest (PIT, QV-095) |
| 7 | `shareholding` | Ownership snapshots |
| 8 | `macro` | Per-series isolation: a missing `FRED_API_KEY` costs the 3 US series only |
| 9 | `news` | No-ops with a clear message when no provider key is set |
| 10 | `tag_news` | Tags untagged news to stocks |
| 11 | `sentiment` | `SENTIMENT_MODEL=dev\|finbert` |
| 12 | `indicators` | Spans the whole window — a single-day run silently zeroes every backtest |
| 13 | `factors_scores` | `--scores-last-day-only` for a fast `/rankings` refresh |
| 14 | `alerts` | Evaluates rules against the scores this run just wrote |
| 15 | `notify` | Delivers pending + previously-failed notifications |
| — | `parquet` | Opt-in (`--only parquet`); needs the `[lake]` extra |

## Caveats

- **Dev data only.** Yahoo prices/fundamentals and free news APIs: partial coverage, not licensed
  for commercial use. The licensed vendor arrives with QV-072.
- **Idempotent.** Every stage upserts and is guarded by a `run_key` ledger entry — re-running is safe.
- **Fails loud.** The first failing stage aborts with exit code 1. `--continue-on-error` records it
  and moves on. `validate` is the usual culprit on dev data; read the failure before skipping it.
- **No Celery worker needed.** Stages call the job functions in-process, synchronously.

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
python syncdatapipeline/resync_all.py --force                # recompute even if already keyed
```

`python -m syncdatapipeline.resync_all` works identically.

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `--days N` | `400` | Days of history; the window ends at the last completed session |
| `--market` | `NSE` | Market code passed to every stage |
| `--index-code` | `NIFTY200` | Index whose constituents the ingest stages iterate |
| `--tolerant` | off | Per-stock isolation for the price load instead of STRICT abort (QV-092) |
| `--scores-last-day-only` | off | Score only the last session; indicators still span the window |
| `--only a,b` | — | Run exactly these stages (may name optional ones) |
| `--skip a,b` | — | Omit these stages |
| `--from STAGE` | — | Resume the default plan at this stage |
| `--force` | off | Release the window's ledger rows first so stages actually recompute |
| `--continue-on-error` | off | Record failures and carry on instead of aborting |
| `--list` | — | Print the plan and exit |

Unknown stage names in `--only`/`--skip`/`--from` exit with the full list rather than silently
running a shorter plan.

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
| 9 | `news` | No-ops when no provider key is set, and when the hour's ledger key already exists |
| 10 | `tag_news` | Tags untagged news to stocks |
| 11 | `sentiment` | `SENTIMENT_MODEL=dev\|finbert` |
| 12 | `indicators` | Spans the whole window — a single-day run silently zeroes every backtest |
| 13 | `factors_scores` | `--scores-last-day-only` for a fast `/rankings` refresh |
| 14 | `alerts` | Evaluates rules against the scores this run just wrote |
| 15 | `notify` | Delivers pending + previously-failed notifications |
| — | `parquet` | Opt-in (`--only parquet`); needs the `[lake]` extra |

## The ledger trap (`--force`)

Every job is guarded by `run_job`, which skips any `run_key` already recorded as succeeded. Correct
for production; wrong for a *resync*, where the whole point is to redo work whose inputs changed.

Two ways this bites:

1. A window an earlier run already covered is skipped, so the resync silently changes nothing.
2. Worse — a job that *succeeds against absent inputs* still records success, locking that date out
   of every future run. Compute indicators for a date whose prices haven't landed and you get a
   permanent hole.

Both happened on 2026-08-01: a 5-day verification run keyed `ind|fac|score` for 07-27→07-31 while
prices ended 07-24, and the full resync an hour later skipped exactly those five sessions — leaving
five sessions of scores on top of no indicators.

`--force` releases the window's ledger rows before running. It marks them `skipped` rather than
deleting (`JobRunLedger.start` reclaims any row that isn't `succeeded`), so the audit row survives
and the re-run overwrites it in place. **Dev only** — it deliberately defeats the idempotency guard.

Stage statuses now distinguish this: `ok` (did the work), `partial` (did some, skipped some),
`no-op` (ledger had everything; nothing recomputed), `failed`. The summary warns loudly on the
middle two instead of folding them into `ok`.

## Caveats

- **Dev data only.** Yahoo prices/fundamentals and free news APIs: partial coverage, not licensed
  for commercial use. The licensed vendor arrives with QV-072.
- **Idempotent, which is not the same as effective.** Every stage upserts and is ledger-guarded, so
  re-running never corrupts anything — but without `--force` it frequently does *nothing*. Read the
  stage statuses, not just the exit code. See [the ledger trap](#the-ledger-trap---force).
- **Fails loud.** The first failing stage aborts with exit code 1; `--continue-on-error` records it
  and moves on.
- **A `validate` failure is real.** It means prices are genuinely missing or stale for the window —
  not dev-data noise. In the 2026-08-01 incident it failed on `coverage, gap` and was the one signal
  that would have caught the problem an hour early. Fix the prices; don't reach for `--skip validate`.
- **Window ends at the last completed session**, never `date.today()` — a weekend has no session, and
  yfinance stamps the in-progress bar with a NaN close (why it's pinned `>=1.5,<2`).
- **No Celery worker needed.** Stages call the job functions in-process, synchronously. Events are
  published, but the pipeline consumers are only registered inside a real worker, so nothing fans out.

## Not yet exercised

Honest status — these paths exist and are typed/linted, but have never actually run:

- **`--tolerant` per-stock isolation.** The flag has been used, but all 200 stocks loaded cleanly
  (`200/200 ok, 0 failed`), so the isolate-and-continue branch has never handled a real Yahoo 429 or
  a delisted ticker.
- **`parquet`.** Opt-in, needs the `[lake]` extra; never invoked.
- **`--force` at full scope.** Verified releasing 15 rows across 3 jobs over a 6-day window; the
  400-day, all-stages release has not been run.

## Tests

`backend/tests/unit/test_resync_all.py` — pure logic, no DB or providers. Covers the status
classification (`ok`/`partial`/`no-op`), the incident's exact 265/270 shape, plan selection
(`--only`/`--skip`/`--from`), and the DAG ordering constraints that must not be silently reordered.

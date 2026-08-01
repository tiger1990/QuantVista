"""Dev-only: re-sync EVERY data pipeline end to end, in dependency order, in one process.

``scripts/dev_backfill.py`` covers the price -> indicator -> factor -> score spine. This runner is
the superset: it also refreshes partitions, the universe, corporate actions, fundamentals,
shareholding, macro series, news + tagging + sentiment, and the alert fire/deliver pair -- so a dev
database that has drifted (or is brand new) can be brought fully current with one command.

Order is the real DAG, not alphabetical, and each edge exists for a reason:

* ``partitions`` first, or rows for a new month land in each table's ``_default`` partition
  (QV-104).
* ``corpactions`` recomputes ``adj_close``, so it must precede ``indicators`` -- otherwise every
  indicator is computed off unadjusted prices across any split in the window.
* ``news -> tag_news -> sentiment`` precedes ``factors_scores`` because ``SentimentFactor`` feeds
  ``scores.sentiment_score`` (QV-046). Run scoring first and the sentiment column is a cycle stale.
* ``fundamentals`` precedes ``factors_scores`` for the same reason, with a PIT twist: fundamentals
  land with their own ``period_end``, so they reach scoring on the run AFTER ingest (QV-095).
* ``alerts`` last -- rules evaluate against the scores this run just wrote.

HONEST CEILING: this drives the DEV providers (Yahoo prices/fundamentals, free news APIs).
Coverage is partial and the data is not licensed for commercial use -- see
``scripts/dev_backfill.py`` for the same caveat. NOT for production. Every stage is idempotent
(upserts + ``run_key`` ledger guards), so re-running is safe and cheap.

Stages fail LOUD by default: the first failure aborts and the exit code is 1.
``--continue-on-error`` records the failure and carries on, which is what you want when one flaky
provider should not cost you the other twelve stages.

``validate`` is the stage most likely to abort a dev run -- it is the real data-quality gate, and
Yahoo dev prices routinely trip its coverage/gap checks over a long window. That abort is the gate
doing its job (do not compute indicators on prices you just failed), so read the failure before
reaching for ``--continue-on-error`` or ``--skip validate``.

Usage (from ``backend/`` with the venv active)::

    python syncdatapipeline/resync_all.py                      # everything, 400 days
    python syncdatapipeline/resync_all.py --list               # show the plan and exit
    python syncdatapipeline/resync_all.py --days 90 --tolerant # fast-ish, per-stock price isolation
    python syncdatapipeline/resync_all.py --only prices,indicators,factors_scores
    python syncdatapipeline/resync_all.py --skip news,sentiment --continue-on-error
    python syncdatapipeline/resync_all.py --only parquet       # opt-in stage ([lake] extra)
    python syncdatapipeline/resync_all.py --force              # recompute even if already keyed

THE LEDGER TRAP (and why ``--force`` exists). Every job here is guarded by ``run_job``, which skips
any ``run_key`` already recorded as succeeded. That is correct for production -- a re-run should not
redo settled work -- but it makes a *resync* a silent no-op over any window an earlier run already
touched, even when the inputs underneath have since changed. Worse, a job that succeeds against
absent inputs (indicators computed for a date whose prices had not landed yet) records success and
locks that date out of every later run.

That is not hypothetical: on 2026-08-01 a five-day verification run keyed ``ind|fac|score`` for
2026-07-27..07-31 while prices still ended 07-24, and the full resync an hour later skipped exactly
those five sessions -- leaving five sessions of scores sitting on top of no indicators at all.
``--force`` releases the window's ledger rows first so the work actually reruns; the summary now
reports ``no-op``/``partial`` rather than folding skips into ``ok``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from quantvista.core.config import get_settings
from quantvista.core.db import privileged_session_scope
from quantvista.core.events import get_event_bus
from quantvista.core.partitions import ensure_month_partitions
from quantvista.jobs.alerts import (
    ALERTS_JOB_NAME,
    DELIVER_JOB_NAME,
    deliver_notifications,
    evaluate_alerts,
)
from quantvista.jobs.compute import COMPUTE_JOB_NAME, backfill_indicators
from quantvista.jobs.ingest import (
    CORPACT_JOB_NAME,
    FUND_JOB_NAME,
    SHP_JOB_NAME,
    backfill_corporate_actions,
    backfill_daily_prices,
    ingest_fundamentals,
    ingest_shareholding,
)
from quantvista.jobs.ingest import (
    JOB_NAME as PRICES_JOB_NAME,
)
from quantvista.jobs.lake import export_prices_parquet
from quantvista.jobs.macro import MACRO_JOB_NAME, sync_macro_series
from quantvista.jobs.news import (
    NEWS_JOB_NAME,
    TAG_JOB_NAME,
    get_news_providers,
    ingest_news,
    tag_news,
)
from quantvista.jobs.quality import VALIDATE_JOB_NAME, validate_prices_range
from quantvista.jobs.scoring import (
    backfill_factors_and_scores,
    compute_factors,
    compute_scores,
)
from quantvista.jobs.sentiment import SENTIMENT_JOB_NAME, score_news
from quantvista.market_data.adapters.yfinance_dev import (
    YFinanceDevProvider,
    yahoo_symbol,
)
from quantvista.market_data.macro import MacroSeries
from quantvista.market_data.services import PriceIngestionService
from quantvista.market_data.trading_calendar import last_completed_session

logging.basicConfig(level=logging.INFO, format="[resync_all] %(message)s")
log = logging.getLogger("resync_all")

DEFAULT_DAYS = 400
DEFAULT_MARKET = "NSE"
DEFAULT_INDEX_CODE = "NIFTY200"
# Only the first 20 per-stock price failures are worth reading; the rest is the same story.
_FAILURE_SAMPLE = 20


@dataclass(frozen=True, slots=True)
class Ctx:
    """Everything a stage needs. Frozen: no stage may rewrite another stage's window."""

    market: str
    index_code: str
    start: date
    end: date
    tolerant: bool
    scores_last_day_only: bool


# Job names whose `jobs_runs` rows `--force` releases. Scoring and lake pass their names to
# run_job as literals (no module constant to import), so those two are spelled out here.
FACTORS_JOB_NAME = "compute_factors"
SCORES_JOB_NAME = "compute_scores"
PARQUET_JOB_NAME = "export_prices_parquet"

STATUS_OK = "ok"
STATUS_NOOP = "no-op"  # ran, but the ledger had already recorded the work -> nothing recomputed
STATUS_PARTIAL = "partial"  # did work, but skipped some units
STATUS_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """What a stage reports back.

    ``status`` exists because "the stage returned without raising" and "the stage did the work"
    are different things: every job here is ledger-guarded, so a stage whose keys already exist
    does nothing at all and still returns cleanly. Collapsing that into a bare "ok" is how a
    resync silently leaves the data it was run to fix exactly as it was.
    """

    detail: str
    status: str = STATUS_OK


@dataclass(frozen=True, slots=True)
class Stage:
    """One pipeline step. ``run`` returns a :class:`StageOutcome` for the summary table."""

    name: str
    what: str
    run: Callable[[Ctx], StageOutcome]
    ledger_jobs: tuple[str, ...] = ()  # jobs_runs.job_name values --force releases
    optional: bool = False  # opt-in only (extra deps / not part of a routine resync)


@dataclass(frozen=True, slots=True)
class StageResult:
    name: str
    status: str  # STATUS_* above
    detail: str
    seconds: float


# --- ledger control ----------------------------------------------------------


def _status_of(job_status: str) -> str:
    """Map a ``JobOutcome`` status onto a stage status ("skipped" is a no-op, not a success)."""
    return STATUS_NOOP if job_status == "skipped" else STATUS_OK


# Every run_key in this codebase embeds an ISO date (`ind:NSE:2026-07-31`,
# `dq:prices:NSE:backfill:2025-06-26:2026-07-31`, `news:2026-08-01T13`), so the window filter reads
# the FIRST date out of the key rather than re-deriving each job's key format here -- duplicating
# those formats is how a release silently stops matching when a job changes its key.
_RELEASE_SQL = text(
    r"""
    UPDATE jobs_runs
       SET status = 'skipped'
     WHERE job_name = ANY(:names)
       AND status = 'succeeded'
       AND substring(run_key from '\d{4}-\d{2}-\d{2}')::date BETWEEN :start AND :end
    RETURNING job_name
    """
)


def release_ledger(job_names: tuple[str, ...], start: date, end: date) -> dict[str, int]:
    """Release succeeded ``jobs_runs`` rows in the window so their jobs will run again.

    Marks them ``skipped`` rather than deleting: ``JobRunLedger.start`` reclaims any row that is
    not ``succeeded`` (``ON CONFLICT ... WHERE status <> 'succeeded'``), so the audit row survives
    and the re-run overwrites it in place. DEV ONLY -- this deliberately defeats the idempotency
    guard that production depends on.
    """
    if not job_names:
        return {}
    with privileged_session_scope() as session:
        rows = session.execute(
            _RELEASE_SQL, {"names": list(job_names), "start": start, "end": end}
        ).all()
    released: dict[str, int] = {}
    for (job_name,) in rows:
        released[job_name] = released.get(job_name, 0) + 1
    return released


# --- stage implementations ---------------------------------------------------


def _stage_partitions(ctx: Ctx) -> StageOutcome:
    """Create monthly partitions ahead of the data (QV-104) BEFORE anything writes rows."""
    with privileged_session_scope() as session:
        result = ensure_month_partitions(session)
    through = result.months[-1].isoformat() if result.months else "n/a"
    return StageOutcome(
        f"{len(result.parents)} parents, {len(result.months)} months, through {through}"
    )


def _stage_universe(ctx: Ctx) -> StageOutcome:
    """Load the full Nifty 200 from the bundled NSE snapshot (QV-092).

    Deliberately NOT ``sync_stock_master`` / ``sync_index_constituents``: the dev provider's
    ``list_universe`` is a 5-symbol convenience list, so a constituent sync against it would CLOSE
    the ~195 other memberships and silently shrink the dev universe to five names.
    """
    # Imported here, not at module scope: `scripts` only resolves once `backend/` is on sys.path
    # (true for `python -m syncdatapipeline.resync_all`, not for `python syncdatapipeline/...`),
    # and the loader calls logging.basicConfig at import time — at module scope that would land
    # first and stamp every line of this run with its `[load_nifty200]` prefix.
    backend_root = Path(__file__).resolve().parent.parent
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from scripts.load_nifty200_universe import DATA_FILE, load_universe, parse_nifty200_csv

    rows = parse_nifty200_csv(DATA_FILE.read_text(encoding="utf-8"))
    with privileged_session_scope() as session:
        stocks, added = load_universe(session, rows, ctx.market)
    return StageOutcome(
        f"{stocks} stocks upserted, {added} new open {DEFAULT_INDEX_CODE} memberships"
    )


def _stage_prices(ctx: Ctx) -> StageOutcome:
    """Backfill daily prices across the window (STRICT, or per-stock tolerant with --tolerant)."""
    if not ctx.tolerant:
        outcome = backfill_daily_prices(ctx.market, start=ctx.start, end=ctx.end)
        return StageOutcome(f"strict: {outcome.status.value}", _status_of(outcome.status.value))

    service = PriceIngestionService(
        YFinanceDevProvider(), get_event_bus(), symbol_mapper=yahoo_symbol
    )
    report = service.ingest(ctx.market, ctx.start, ctx.end, index_code=ctx.index_code)
    for symbol, err in report.failures[:_FAILURE_SAMPLE]:
        log.warning("  dropped %s: %s", symbol, err[:120])
    # The tolerant path calls the service directly, so no ledger key is involved -- it always
    # does the work, and a zero-row result means Yahoo gave us nothing, not that we skipped.
    return StageOutcome(
        f"tolerant: {report.stocks_ok}/{report.stocks_total} ok, "
        f"{report.stocks_no_data} no-data, {report.stocks_failed} failed, "
        f"{report.rows_upserted} rows"
    )


def _stage_validate(ctx: Ctx) -> StageOutcome:
    """Run the data-quality gate over the whole backfilled window, not just the last session."""
    outcome = validate_prices_range(
        ctx.market, start=ctx.start, end=ctx.end, index_code=ctx.index_code
    )
    return StageOutcome(outcome.status.value, _status_of(outcome.status.value))


def _stage_corpactions(ctx: Ctx) -> StageOutcome:
    """Backfill corporate actions and recompute ``adj_close`` -- must precede indicators."""
    outcome = backfill_corporate_actions(
        ctx.market, start=ctx.start, end=ctx.end, index_code=ctx.index_code
    )
    return StageOutcome(outcome.status.value, _status_of(outcome.status.value))


def _stage_fundamentals(ctx: Ctx) -> StageOutcome:
    """Poll + version the latest fundamentals filings (bitemporal, QV-022/QV-095)."""
    status = str(ingest_fundamentals(ctx.market, ctx.end.isoformat()))
    return StageOutcome(status, _status_of(status))


def _stage_shareholding(ctx: Ctx) -> StageOutcome:
    """Poll + upsert the latest ownership snapshots (PIT by ``as_of_date``, QV-023)."""
    status = str(ingest_shareholding(ctx.market, ctx.end.isoformat()))
    return StageOutcome(status, _status_of(status))


def _stage_macro(ctx: Ctx) -> StageOutcome:
    """Sync every canonical macro series.

    Per-series isolation on purpose: FRED needs ``FRED_API_KEY`` while World Bank needs no key, so
    an unset key should cost you the three US series -- not the three India ones behind them.
    """
    ok: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for series in MacroSeries:
        try:
            status = str(sync_macro_series(series.value, ctx.end.isoformat()))
            (skipped if status == "skipped" else ok).append(series.value)
        except Exception as exc:  # noqa: BLE001 -- one series must not sink the rest
            failed.append(series.value)
            log.warning("  macro %s failed: %s", series.value, str(exc)[:160])
    total = len(ok) + len(skipped) + len(failed)
    detail = f"{len(ok)}/{total} synced"
    if skipped:
        detail += f", {len(skipped)} already-run"
    if failed:
        detail += f" (failed: {', '.join(failed)})"
    if not ok:
        return StageOutcome(detail, STATUS_NOOP)
    return StageOutcome(detail, STATUS_PARTIAL if (skipped or failed) else STATUS_OK)


def _stage_news(ctx: Ctx) -> StageOutcome:
    """Ingest market news from every provider that has an API key configured (QV-041)."""
    providers = get_news_providers()
    if not providers:
        return StageOutcome(
            "no providers configured (set NEWS_API_ORG_API_KEY / GNEWS_API_KEY / ...)", STATUS_NOOP
        )
    status = str(ingest_news())
    return StageOutcome(f"{len(providers)} providers: {status}", _status_of(status))


def _stage_tag_news(ctx: Ctx) -> StageOutcome:
    """Tag whatever news is currently untagged to stocks (QV-042)."""
    status = str(tag_news())
    return StageOutcome(status, _status_of(status))


def _stage_sentiment(ctx: Ctx) -> StageOutcome:
    """Score untagged-by-sentiment news with the configured model (dev lexicon or FinBERT)."""
    status = str(score_news())
    return StageOutcome(f"model={get_settings().sentiment_model}: {status}", _status_of(status))


def _stage_indicators(ctx: Ctx) -> StageOutcome:
    """Compute indicators across the WHOLE window (QV-105).

    A single-day indicator run behind a year of prices is the classic silent trap: backtests rank
    off ``technical_indicators`` at every rebalance date, select nothing, and report 0.00% on each
    strategy metric while the benchmark -- pure price maths -- looks fine. Nothing errors.
    """
    outcomes = backfill_indicators(ctx.market, start=ctx.start, end=ctx.end)
    succeeded = sum(o.status.value == "succeeded" for o in outcomes)
    skipped = len(outcomes) - succeeded
    detail = f"{succeeded}/{len(outcomes)} sessions computed"
    if skipped:
        # This is the exact shape of the 2026-08-01 incident: prices land, but sessions an
        # earlier run already keyed stay untouched, leaving indicators behind the price head.
        detail += f", {skipped} already-run (use --force to recompute)"
    if not succeeded:
        return StageOutcome(detail, STATUS_NOOP)
    return StageOutcome(detail, STATUS_PARTIAL if skipped else STATUS_OK)


def _stage_factors_scores(ctx: Ctx) -> StageOutcome:
    """Compute factors + scores across the window (or only the last session, for speed)."""
    if ctx.scores_last_day_only:
        target = ctx.end.isoformat()
        factors = str(compute_factors(ctx.market, target))
        scores = str(compute_scores(ctx.market, target))
        worked = "succeeded" in (factors, scores)
        return StageOutcome(
            f"last session only: factors={factors}, scores={scores}",
            STATUS_OK if worked else STATUS_NOOP,
        )
    pairs = backfill_factors_and_scores(ctx.market, start=ctx.start, end=ctx.end)
    computed = sum(f.status.value == "succeeded" for f, _ in pairs)
    skipped = len(pairs) - computed
    detail = f"{computed}/{len(pairs)} sessions computed"
    if skipped:
        detail += f", {skipped} already-run (use --force to recompute)"
    if not computed:
        return StageOutcome(detail, STATUS_NOOP)
    return StageOutcome(detail, STATUS_PARTIAL if skipped else STATUS_OK)


def _stage_alerts(ctx: Ctx) -> StageOutcome:
    """Evaluate every tenant's active rules against the scores this run just wrote (QV-048)."""
    status = str(evaluate_alerts(ctx.end.isoformat(), "scores"))
    return StageOutcome(status, _status_of(status))


def _stage_notify(ctx: Ctx) -> StageOutcome:
    """Deliver pending + previously-failed alert notifications (QV-049)."""
    status = str(deliver_notifications())
    return StageOutcome(status, _status_of(status))


def _stage_parquet(ctx: Ctx) -> StageOutcome:
    """Offload historical prices to Parquet partitions (QV-067). Needs the ``[lake]`` extra."""
    status = str(export_prices_parquet(ctx.market))
    return StageOutcome(status, _status_of(status))


# The DAG. Order is load-bearing -- see the module docstring for why each edge exists.
STAGES: tuple[Stage, ...] = (
    # partitions/universe run no ledger-guarded job, so they have no keys to release.
    Stage("partitions", "ensure monthly partitions exist", _stage_partitions),
    Stage("universe", "load the Nifty 200 stocks + membership", _stage_universe),
    Stage("prices", "backfill daily prices", _stage_prices, (PRICES_JOB_NAME,)),
    Stage(
        "validate", "data-quality gate over the price window", _stage_validate, (VALIDATE_JOB_NAME,)
    ),
    Stage(
        "corpactions",
        "corporate actions + adj_close recompute",
        _stage_corpactions,
        (CORPACT_JOB_NAME,),
    ),
    Stage("fundamentals", "versioned fundamentals filings", _stage_fundamentals, (FUND_JOB_NAME,)),
    Stage("shareholding", "ownership snapshots", _stage_shareholding, (SHP_JOB_NAME,)),
    Stage("macro", "macro series (FRED + World Bank)", _stage_macro, (MACRO_JOB_NAME,)),
    Stage("news", "ingest news from enabled providers", _stage_news, (NEWS_JOB_NAME,)),
    Stage("tag_news", "tag news to stocks", _stage_tag_news, (TAG_JOB_NAME,)),
    Stage("sentiment", "score news sentiment", _stage_sentiment, (SENTIMENT_JOB_NAME,)),
    Stage(
        "indicators",
        "technical indicators across the window",
        _stage_indicators,
        (COMPUTE_JOB_NAME,),
    ),
    Stage(
        "factors_scores",
        "factors + composite scores",
        _stage_factors_scores,
        (FACTORS_JOB_NAME, SCORES_JOB_NAME),
    ),
    Stage("alerts", "evaluate alert rules", _stage_alerts, (ALERTS_JOB_NAME,)),
    Stage("notify", "deliver pending notifications", _stage_notify, (DELIVER_JOB_NAME,)),
    Stage(
        "parquet",
        "export prices to Parquet [lake]",
        _stage_parquet,
        (PARQUET_JOB_NAME,),
        optional=True,
    ),
)

STAGE_NAMES: tuple[str, ...] = tuple(s.name for s in STAGES)


# --- plan selection ----------------------------------------------------------


def _parse_names(raw: str | None, flag: str) -> list[str]:
    """Split a comma-separated stage list, rejecting unknown names loudly."""
    if not raw:
        return []
    names = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [n for n in names if n not in STAGE_NAMES]
    if unknown:
        raise SystemExit(f"{flag}: unknown stage(s) {unknown}. Known: {', '.join(STAGE_NAMES)}")
    return names


def select_stages(only: list[str], skip: list[str], start_from: str | None) -> tuple[Stage, ...]:
    """Resolve --only / --skip / --from into the ordered stage list to run.

    ``--only`` is explicit, so it includes optional stages; the default plan does not. Pure: no I/O,
    which is what makes the selection directly testable.
    """
    if only:
        chosen = [s for s in STAGES if s.name in only]
    else:
        chosen = [s for s in STAGES if not s.optional]
        if start_from:
            offset = STAGE_NAMES.index(start_from)
            chosen = [s for s in chosen if STAGE_NAMES.index(s.name) >= offset]
    return tuple(s for s in chosen if s.name not in skip)


def _print_plan(stages: tuple[Stage, ...], ctx: Ctx) -> None:
    log.info("plan: %s..%s (%s), %d stages", ctx.start, ctx.end, ctx.market, len(stages))
    for index, stage in enumerate(stages, start=1):
        log.info("  %2d. %-15s %s", index, stage.name, stage.what)


def _print_summary(results: list[StageResult]) -> None:
    log.info("-" * 78)
    log.info("%-15s %-8s %8s  %s", "STAGE", "STATUS", "SECONDS", "DETAIL")
    for result in results:
        log.info("%-15s %-8s %8.1f  %s", result.name, result.status, result.seconds, result.detail)
    failed = [r.name for r in results if r.status == STATUS_FAILED]
    noop = [r.name for r in results if r.status == STATUS_NOOP]
    partial = [r.name for r in results if r.status == STATUS_PARTIAL]
    total = sum(r.seconds for r in results)
    log.info("-" * 78)
    if failed:
        log.error("%d/%d stages FAILED in %.1fs: %s", len(failed), len(results), total, failed)
    else:
        log.info("%d stages finished in %.1fs", len(results), total)
    # Loud on purpose: a run whose stages all "finished" can still have changed nothing, and that
    # is indistinguishable from success unless it is said out loud.
    if noop:
        log.warning("NO-OP (ledger already had these keys; nothing recomputed): %s", noop)
    if partial:
        log.warning("PARTIAL (some units were already-run and left untouched): %s", partial)
    if noop or partial:
        log.warning("re-run with --force to recompute the window regardless of the ledger")


# --- runner ------------------------------------------------------------------


def run_stages(
    stages: tuple[Stage, ...], ctx: Ctx, *, continue_on_error: bool
) -> list[StageResult]:
    """Run each stage in order, timing it. Aborts on the first failure unless told otherwise."""
    results: list[StageResult] = []
    for index, stage in enumerate(stages, start=1):
        log.info("[%d/%d] %s -- %s", index, len(stages), stage.name, stage.what)
        started = time.monotonic()
        try:
            outcome = stage.run(ctx)
        except Exception as exc:  # noqa: BLE001 -- summarised below, re-raised unless tolerant
            elapsed = time.monotonic() - started
            results.append(StageResult(stage.name, STATUS_FAILED, str(exc)[:200], elapsed))
            log.error("  %s FAILED after %.1fs: %s", stage.name, elapsed, exc)
            if not continue_on_error:
                _print_summary(results)
                raise
            continue
        elapsed = time.monotonic() - started
        results.append(StageResult(stage.name, outcome.status, outcome.detail, elapsed))
        log.info("  %s %s (%.1fs): %s", stage.name, outcome.status, elapsed, outcome.detail)
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-sync every QuantVista dev data pipeline in dependency order.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Stages: " + ", ".join(STAGE_NAMES),
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS, help=f"days of history (default {DEFAULT_DAYS})"
    )
    parser.add_argument("--market", default=DEFAULT_MARKET)
    parser.add_argument("--index-code", default=DEFAULT_INDEX_CODE)
    parser.add_argument(
        "--tolerant",
        action="store_true",
        help="per-stock isolation for the price load (full Nifty 200; QV-092)",
    )
    parser.add_argument(
        "--scores-last-day-only",
        action="store_true",
        help=(
            "score only the last session (fast; enough for /rankings). Indicators still span the "
            "window, since backtests need them at every rebalance date."
        ),
    )
    parser.add_argument("--only", help="comma-separated stages to run (includes optional ones)")
    parser.add_argument("--skip", help="comma-separated stages to omit")
    parser.add_argument("--from", dest="start_from", help="resume the default plan at this stage")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "release this window's succeeded jobs_runs rows first, so every selected stage "
            "recomputes instead of being skipped by the ledger (DEV ONLY)"
        ),
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="record failures and keep going instead of aborting on the first one",
    )
    parser.add_argument("--list", action="store_true", help="print the plan and exit")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    only = _parse_names(args.only, "--only")
    skip = _parse_names(args.skip, "--skip")
    if args.start_from and args.start_from not in STAGE_NAMES:
        raise SystemExit(f"--from: unknown stage {args.start_from!r}")

    stages = select_stages(only, skip, args.start_from)
    if not stages:
        raise SystemExit("nothing to run: --only/--skip selected an empty plan")

    end = last_completed_session(date.today())
    ctx = Ctx(
        market=args.market,
        index_code=args.index_code,
        start=end - timedelta(days=args.days),
        end=end,
        tolerant=args.tolerant,
        scores_last_day_only=args.scores_last_day_only,
    )

    _print_plan(stages, ctx)
    if args.list:
        return

    if args.force:
        names = tuple({job for stage in stages for job in stage.ledger_jobs})
        # Release through TODAY, not ctx.end: hour/second-keyed jobs (news, tag_news, notify) key
        # off now(), which is past the last completed session whenever the market is shut.
        released = release_ledger(names, ctx.start, date.today())
        total = sum(released.values())
        log.info("--force: released %d ledger rows across %d jobs", total, len(released))
        for job_name, count in sorted(released.items()):
            log.info("    %-28s %d", job_name, count)

    results = run_stages(stages, ctx, continue_on_error=args.continue_on_error)
    _print_summary(results)
    if any(r.status == "failed" for r in results):
        raise SystemExit(1)
    log.info("done -- /rankings?market=%s should return rows for %s", ctx.market, ctx.end)


if __name__ == "__main__":
    main()

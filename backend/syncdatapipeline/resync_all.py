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

from quantvista.core.config import get_settings
from quantvista.core.db import privileged_session_scope
from quantvista.core.events import get_event_bus
from quantvista.core.partitions import ensure_month_partitions
from quantvista.jobs.alerts import deliver_notifications, evaluate_alerts
from quantvista.jobs.compute import backfill_indicators
from quantvista.jobs.ingest import (
    backfill_corporate_actions,
    backfill_daily_prices,
    ingest_fundamentals,
    ingest_shareholding,
)
from quantvista.jobs.lake import export_prices_parquet
from quantvista.jobs.macro import sync_macro_series
from quantvista.jobs.news import get_news_providers, ingest_news, tag_news
from quantvista.jobs.quality import validate_prices_range
from quantvista.jobs.scoring import (
    backfill_factors_and_scores,
    compute_factors,
    compute_scores,
)
from quantvista.jobs.sentiment import score_news
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


@dataclass(frozen=True, slots=True)
class Stage:
    """One pipeline step. ``run`` returns a one-line result for the summary table."""

    name: str
    what: str
    run: Callable[[Ctx], str]
    optional: bool = False  # opt-in only (extra deps / not part of a routine resync)


@dataclass(frozen=True, slots=True)
class StageResult:
    name: str
    status: str  # "ok" | "failed" | "skipped"
    detail: str
    seconds: float


# --- stage implementations ---------------------------------------------------


def _stage_partitions(ctx: Ctx) -> str:
    """Create monthly partitions ahead of the data (QV-104) BEFORE anything writes rows."""
    with privileged_session_scope() as session:
        result = ensure_month_partitions(session)
    through = result.months[-1].isoformat() if result.months else "n/a"
    return f"{len(result.parents)} parents, {len(result.months)} months, through {through}"


def _stage_universe(ctx: Ctx) -> str:
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
    return f"{stocks} stocks upserted, {added} new open {DEFAULT_INDEX_CODE} memberships"


def _stage_prices(ctx: Ctx) -> str:
    """Backfill daily prices across the window (STRICT, or per-stock tolerant with --tolerant)."""
    if not ctx.tolerant:
        outcome = backfill_daily_prices(ctx.market, start=ctx.start, end=ctx.end)
        return f"strict: {outcome.status.value}"

    service = PriceIngestionService(
        YFinanceDevProvider(), get_event_bus(), symbol_mapper=yahoo_symbol
    )
    report = service.ingest(ctx.market, ctx.start, ctx.end, index_code=ctx.index_code)
    for symbol, err in report.failures[:_FAILURE_SAMPLE]:
        log.warning("  dropped %s: %s", symbol, err[:120])
    return (
        f"tolerant: {report.stocks_ok}/{report.stocks_total} ok, "
        f"{report.stocks_no_data} no-data, {report.stocks_failed} failed, "
        f"{report.rows_upserted} rows"
    )


def _stage_validate(ctx: Ctx) -> str:
    """Run the data-quality gate over the whole backfilled window, not just the last session."""
    outcome = validate_prices_range(
        ctx.market, start=ctx.start, end=ctx.end, index_code=ctx.index_code
    )
    return outcome.status.value


def _stage_corpactions(ctx: Ctx) -> str:
    """Backfill corporate actions and recompute ``adj_close`` -- must precede indicators."""
    outcome = backfill_corporate_actions(
        ctx.market, start=ctx.start, end=ctx.end, index_code=ctx.index_code
    )
    return outcome.status.value


def _stage_fundamentals(ctx: Ctx) -> str:
    """Poll + version the latest fundamentals filings (bitemporal, QV-022/QV-095)."""
    return str(ingest_fundamentals(ctx.market, ctx.end.isoformat()))


def _stage_shareholding(ctx: Ctx) -> str:
    """Poll + upsert the latest ownership snapshots (PIT by ``as_of_date``, QV-023)."""
    return str(ingest_shareholding(ctx.market, ctx.end.isoformat()))


def _stage_macro(ctx: Ctx) -> str:
    """Sync every canonical macro series.

    Per-series isolation on purpose: FRED needs ``FRED_API_KEY`` while World Bank needs no key, so
    an unset key should cost you the three US series -- not the three India ones behind them.
    """
    ok: list[str] = []
    failed: list[str] = []
    for series in MacroSeries:
        try:
            sync_macro_series(series.value, ctx.end.isoformat())
            ok.append(series.value)
        except Exception as exc:  # noqa: BLE001 -- one series must not sink the rest
            failed.append(series.value)
            log.warning("  macro %s failed: %s", series.value, str(exc)[:160])
    detail = f"{len(ok)}/{len(ok) + len(failed)} series"
    return detail if not failed else f"{detail} (failed: {', '.join(failed)})"


def _stage_news(ctx: Ctx) -> str:
    """Ingest market news from every provider that has an API key configured (QV-041)."""
    providers = get_news_providers()
    if not providers:
        return "no providers configured (set NEWS_API_ORG_API_KEY / GNEWS_API_KEY / ...)"
    return f"{len(providers)} providers: {ingest_news()}"


def _stage_tag_news(ctx: Ctx) -> str:
    """Tag whatever news is currently untagged to stocks (QV-042)."""
    return str(tag_news())


def _stage_sentiment(ctx: Ctx) -> str:
    """Score untagged-by-sentiment news with the configured model (dev lexicon or FinBERT)."""
    return f"model={get_settings().sentiment_model}: {score_news()}"


def _stage_indicators(ctx: Ctx) -> str:
    """Compute indicators across the WHOLE window (QV-105).

    A single-day indicator run behind a year of prices is the classic silent trap: backtests rank
    off ``technical_indicators`` at every rebalance date, select nothing, and report 0.00% on each
    strategy metric while the benchmark -- pure price maths -- looks fine. Nothing errors.
    """
    outcomes = backfill_indicators(ctx.market, start=ctx.start, end=ctx.end)
    succeeded = sum(o.status.value == "succeeded" for o in outcomes)
    return f"{succeeded}/{len(outcomes)} sessions succeeded"


def _stage_factors_scores(ctx: Ctx) -> str:
    """Compute factors + scores across the window (or only the last session, for speed)."""
    if ctx.scores_last_day_only:
        target = ctx.end.isoformat()
        factors = compute_factors(ctx.market, target)
        scores = compute_scores(ctx.market, target)
        return f"last session only: factors={factors}, scores={scores}"
    pairs = backfill_factors_and_scores(ctx.market, start=ctx.start, end=ctx.end)
    return f"{len(pairs)} sessions"


def _stage_alerts(ctx: Ctx) -> str:
    """Evaluate every tenant's active rules against the scores this run just wrote (QV-048)."""
    return str(evaluate_alerts(ctx.end.isoformat(), "scores"))


def _stage_notify(ctx: Ctx) -> str:
    """Deliver pending + previously-failed alert notifications (QV-049)."""
    return str(deliver_notifications())


def _stage_parquet(ctx: Ctx) -> str:
    """Offload historical prices to Parquet partitions (QV-067). Needs the ``[lake]`` extra."""
    return str(export_prices_parquet(ctx.market))


# The DAG. Order is load-bearing -- see the module docstring for why each edge exists.
STAGES: tuple[Stage, ...] = (
    Stage("partitions", "ensure monthly partitions exist", _stage_partitions),
    Stage("universe", "load the Nifty 200 stocks + membership", _stage_universe),
    Stage("prices", "backfill daily prices", _stage_prices),
    Stage("validate", "data-quality gate over the price window", _stage_validate),
    Stage("corpactions", "corporate actions + adj_close recompute", _stage_corpactions),
    Stage("fundamentals", "versioned fundamentals filings", _stage_fundamentals),
    Stage("shareholding", "ownership snapshots", _stage_shareholding),
    Stage("macro", "macro series (FRED + World Bank)", _stage_macro),
    Stage("news", "ingest news from enabled providers", _stage_news),
    Stage("tag_news", "tag news to stocks", _stage_tag_news),
    Stage("sentiment", "score news sentiment", _stage_sentiment),
    Stage("indicators", "technical indicators across the window", _stage_indicators),
    Stage("factors_scores", "factors + composite scores", _stage_factors_scores),
    Stage("alerts", "evaluate alert rules", _stage_alerts),
    Stage("notify", "deliver pending notifications", _stage_notify),
    Stage("parquet", "export prices to Parquet [lake]", _stage_parquet, optional=True),
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
    failed = [r.name for r in results if r.status == "failed"]
    total = sum(r.seconds for r in results)
    log.info("-" * 78)
    if failed:
        log.error("%d/%d stages FAILED in %.1fs: %s", len(failed), len(results), total, failed)
    else:
        log.info("all %d stages ok in %.1fs", len(results), total)


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
            detail = stage.run(ctx)
        except Exception as exc:  # noqa: BLE001 -- summarised below, re-raised unless tolerant
            elapsed = time.monotonic() - started
            results.append(StageResult(stage.name, "failed", str(exc)[:200], elapsed))
            log.error("  %s FAILED after %.1fs: %s", stage.name, elapsed, exc)
            if not continue_on_error:
                _print_summary(results)
                raise
            continue
        elapsed = time.monotonic() - started
        results.append(StageResult(stage.name, "ok", detail, elapsed))
        log.info("  %s ok (%.1fs): %s", stage.name, elapsed, detail)
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

    results = run_stages(stages, ctx, continue_on_error=args.continue_on_error)
    _print_summary(results)
    if any(r.status == "failed" for r in results):
        raise SystemExit(1)
    log.info("done -- /rankings?market=%s should return rows for %s", ctx.market, ctx.end)


if __name__ == "__main__":
    main()

"""Unit tests for the dev resync runner (``syncdatapipeline/resync_all.py``).

The bug these guard against is specific and was live on 2026-08-01: every job in the pipeline is
ledger-guarded, so a stage whose run keys already exist does *nothing* and still returns without
raising. The runner reported that as ``ok``, so a full resync could leave indicators five sessions
behind the prices it had just ingested and look like a clean run in the summary.

Pure logic only -- no DB, no providers.
"""

from __future__ import annotations

from datetime import date

import pytest
from syncdatapipeline.resync_all import (
    STAGE_NAMES,
    STATUS_NOOP,
    STATUS_OK,
    STATUS_PARTIAL,
    Ctx,
    _stage_factors_scores,
    _stage_indicators,
    _status_of,
    select_stages,
)


@pytest.fixture
def ctx() -> Ctx:
    return Ctx(
        market="NSE",
        index_code="NIFTY200",
        start=date(2026, 7, 25),
        end=date(2026, 7, 31),
        tolerant=False,
        scores_last_day_only=False,
    )


class _FakeStatus:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeOutcome:
    def __init__(self, value: str) -> None:
        self.status = _FakeStatus(value)


# --- job status -> stage status ---------------------------------------------


def test_skipped_job_maps_to_noop_not_ok() -> None:
    assert _status_of("skipped") == STATUS_NOOP


def test_succeeded_job_maps_to_ok() -> None:
    assert _status_of("succeeded") == STATUS_OK


# --- indicators: the stage whose silent skips caused the incident ------------


def test_indicators_all_skipped_reports_noop(ctx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    """A window the ledger already covered must NOT be reported as a success."""
    monkeypatch.setattr(
        "syncdatapipeline.resync_all.backfill_indicators",
        lambda *a, **k: [_FakeOutcome("skipped") for _ in range(5)],
    )
    outcome = _stage_indicators(ctx)
    assert outcome.status == STATUS_NOOP
    assert "0/5 sessions computed" in outcome.detail
    assert "--force" in outcome.detail


def test_indicators_some_skipped_reports_partial(ctx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real incident shape: 265 computed, the 5 most recent silently left behind."""
    outcomes = [_FakeOutcome("succeeded")] * 265 + [_FakeOutcome("skipped")] * 5
    monkeypatch.setattr("syncdatapipeline.resync_all.backfill_indicators", lambda *a, **k: outcomes)
    outcome = _stage_indicators(ctx)
    assert outcome.status == STATUS_PARTIAL
    assert "265/270 sessions computed" in outcome.detail
    assert "5 already-run" in outcome.detail


def test_indicators_all_computed_reports_ok(ctx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "syncdatapipeline.resync_all.backfill_indicators",
        lambda *a, **k: [_FakeOutcome("succeeded") for _ in range(5)],
    )
    outcome = _stage_indicators(ctx)
    assert outcome.status == STATUS_OK
    assert "already-run" not in outcome.detail


def test_factors_scores_all_skipped_reports_noop(ctx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    pairs = [(_FakeOutcome("skipped"), _FakeOutcome("skipped")) for _ in range(5)]
    monkeypatch.setattr(
        "syncdatapipeline.resync_all.backfill_factors_and_scores", lambda *a, **k: pairs
    )
    outcome = _stage_factors_scores(ctx)
    assert outcome.status == STATUS_NOOP


# --- plan selection ----------------------------------------------------------


def test_default_plan_excludes_optional_stages() -> None:
    names = [s.name for s in select_stages([], [], None)]
    assert "parquet" not in names
    assert names[0] == "partitions"


def test_only_can_select_an_optional_stage() -> None:
    assert [s.name for s in select_stages(["parquet"], [], None)] == ["parquet"]


def test_skip_removes_a_stage() -> None:
    names = [s.name for s in select_stages([], ["news"], None)]
    assert "news" not in names


def test_from_resumes_at_a_stage_and_keeps_dag_order() -> None:
    names = [s.name for s in select_stages([], [], "indicators")]
    assert names == ["indicators", "factors_scores", "alerts", "notify"]


def test_corpactions_precedes_indicators_in_the_dag() -> None:
    """adj_close is recomputed by corpactions; indicators computed before it are wrong."""
    assert STAGE_NAMES.index("corpactions") < STAGE_NAMES.index("indicators")


def test_scoring_inputs_precede_scoring_in_the_dag() -> None:
    """Sentiment and fundamentals both feed the composite score."""
    for upstream in ("sentiment", "fundamentals", "indicators"):
        assert STAGE_NAMES.index(upstream) < STAGE_NAMES.index("factors_scores")

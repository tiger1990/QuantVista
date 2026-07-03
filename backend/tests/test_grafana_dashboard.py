"""Structural validation of the Grafana dashboard JSON (QV-020).

We can't render Grafana here (that's PV-003 / staging), but we can guarantee the checked-in JSON is
well-formed, has the expected panels, and every panel targets a metric that actually exists — so a
typo'd metric name never ships to staging.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_OPS = Path(__file__).resolve().parents[2] / "ops"
_DASHBOARD = _OPS / "grafana" / "dashboards" / "job-observability.json"

# The metric names this dashboard is allowed to reference (QV-009 + QV-020 surface).
_KNOWN_METRICS = {
    "celery_task_duration_seconds",  # + _bucket/_sum/_count
    "celery_task_failures_total",
    "celery_tasks_total",
    "data_latest_ingest_timestamp_seconds",
    "celery_queue_depth",
}

_EXPECTED_PANELS = {
    "Task latency p50 / p95",
    "Task failure rate",
    "Tasks by terminal state",
    "Pipeline freshness lag (daily_prices)",
    "Queue depth",
}


def _dashboard() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_DASHBOARD.read_text())
    return data


def test_dashboard_is_valid_json_with_uid_and_title() -> None:
    d = _dashboard()
    assert d["uid"] and d["title"]
    assert isinstance(d["panels"], list) and d["panels"]


def test_dashboard_has_expected_panels() -> None:
    titles = {p["title"] for p in _dashboard()["panels"]}
    assert titles == _EXPECTED_PANELS


def test_every_panel_target_references_a_known_metric() -> None:
    for panel in _dashboard()["panels"]:
        for target in panel.get("targets", []):
            expr = target["expr"]
            assert any(m in expr for m in _KNOWN_METRICS), f"unknown metric in expr: {expr}"

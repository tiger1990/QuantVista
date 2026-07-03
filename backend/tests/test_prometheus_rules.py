"""Prometheus config + alert-rule validation via promtool (QV-020).

`promtool test rules` is a deterministic, server-free proof of the alert logic (fresh -> inactive,
stale -> firing, etc.). promtool ships with the Prometheus binary; if it isn't on this machine the
tests SKIP (like the DB integration tests) rather than hard-fail — CI/other machines stay green.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_OPS = Path(__file__).resolve().parents[2] / "ops" / "prometheus"

_EXPECTED_ALERTS = {"PipelineFreshnessLagHigh", "JobFailureRateHigh", "QueueBacklogHigh"}


def _load(name: str) -> Any:
    return yaml.safe_load((_OPS / name).read_text())


# --- Always-on structural checks (no promtool needed) -------------------------
def test_alert_rules_are_well_formed_yaml_with_expected_alerts() -> None:
    groups = _load("alerts.yml")["groups"]
    alerts = {r["alert"]: r for g in groups for r in g["rules"]}
    assert set(alerts) == _EXPECTED_ALERTS
    for rule in alerts.values():  # every alert carries an expr + a runbook annotation
        assert rule["expr"] and rule["annotations"]["runbook"]


def test_rule_test_file_targets_the_rules() -> None:
    doc = _load("alerts_test.yml")
    assert "alerts.yml" in doc["rule_files"]
    tested = {c["alertname"] for t in doc["tests"] for c in t["alert_rule_test"]}
    assert tested == _EXPECTED_ALERTS  # every alert has at least one promtool case


def _promtool() -> str | None:
    found = shutil.which("promtool")
    if found:
        return found
    # Homebrew installs to the Cellar; check the standard prefixes too.
    for prefix in ("/opt/homebrew/bin/promtool", "/usr/local/bin/promtool"):
        if Path(prefix).exists():
            return prefix
    return None


_PROMTOOL = _promtool()
requires_promtool = pytest.mark.skipif(_PROMTOOL is None, reason="promtool not installed")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    assert _PROMTOOL is not None
    return subprocess.run(
        [_PROMTOOL, *args], capture_output=True, text=True, cwd=str(_OPS), timeout=60
    )


@requires_promtool
def test_prometheus_config_is_valid() -> None:
    result = _run("check", "config", "prometheus.yml")
    assert result.returncode == 0, result.stdout + result.stderr


@requires_promtool
def test_alert_rules_are_valid() -> None:
    result = _run("check", "rules", "alerts.yml")
    assert result.returncode == 0, result.stdout + result.stderr


@requires_promtool
def test_alert_rules_fire_as_expected() -> None:
    # Deterministic: fresh->inactive, stale->firing, failures->firing, backlog->firing/inactive.
    result = _run("test", "rules", "alerts_test.yml")
    assert result.returncode == 0, result.stdout + result.stderr

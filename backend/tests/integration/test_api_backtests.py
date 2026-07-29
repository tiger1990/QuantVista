"""Backtest async API end-to-end (QV-062) — real app + PG + auth + the run_backtest task.

Covers: submit → 202 queued, poll, the runner transitioning queued→succeeded (QV-065 engine),
idempotent re-run, the two-tier entitlement (Free 403, Pro ≤1y 202 / >1y 403, Quant full 202), a bad
spec → 422, and cross-tenant / unknown → 404. The ``enqueue`` seam is patched to a no-op so the API
test needs no broker; the runner is then invoked directly (the worker's job).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from quantvista.api.app import create_app
from quantvista.jobs.backtest import run_backtest

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"

_SHORT = {"start": "2020-01-01", "end": "2020-06-30"}  # 181 days (Pro preset)
_LONG = {"start": "2018-01-01", "end": "2020-12-31"}  # ~3y (needs backtest_full)


def _spec(**over: Any) -> dict[str, Any]:
    base = {
        "type": "factor_strategy",
        "universe": "NIFTY200",
        "rules": {"rank_by": "composite", "top_n": 20, "rebalance": "monthly"},
        "costs_bps": 15,
        "benchmark": "NIFTY200_TRI",
        **_SHORT,
    }
    base.update(over)
    return base


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(client: TestClient) -> tuple[str, str]:
    email = f"bt-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


@pytest.fixture(autouse=True)
def _no_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep POST /backtests broker-free: the `enqueue` seam becomes a no-op (we run the task
    directly to simulate the worker)."""
    monkeypatch.setattr("quantvista.api.routes_backtests.enqueue", lambda *a, **k: None)


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[dict[str, Any]]:
    client = TestClient(create_app(), base_url="https://testserver")
    email_free, token_free = _register(client)
    email_pro, token_pro = _register(client)
    email_quant, token_quant = _register(client)
    email_other, token_other = _register(client)
    with admin_engine.begin() as conn:
        for email, plan in ((email_pro, "pro"), (email_quant, "quant"), (email_other, "pro")):
            conn.execute(
                text(
                    "UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE code = :plan) "
                    "WHERE tenant_id IN (SELECT m.tenant_id FROM memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
                ),
                {"e": email, "plan": plan},
            )
    yield {
        "client": client,
        "free": token_free,
        "pro": token_pro,
        "quant": token_quant,
        "other": token_other,
    }
    with admin_engine.begin() as conn:
        for email in (email_free, email_pro, email_quant, email_other):
            conn.execute(
                text(
                    "DELETE FROM tenants WHERE id IN (SELECT m.tenant_id FROM memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
                ),
                {"e": email},
            )
            conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


def _submit(client: TestClient, token: str, **over: Any) -> Any:
    return client.post("/api/v1/backtests", json={"spec": _spec(**over)}, headers=_h(token))


# --- entitlement gating -----------------------------------------------------


def test_free_tier_submit_forbidden(api: dict[str, Any]) -> None:
    r = _submit(api["client"], api["free"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "entitlement_exceeded"


def test_pro_short_range_queued(api: dict[str, Any]) -> None:
    r = _submit(api["client"], api["pro"])
    assert r.status_code == 202
    data = r.json()["data"]
    assert data["status"] == "queued" and data["id"]


def test_pro_long_range_forbidden(api: dict[str, Any]) -> None:
    r = _submit(api["client"], api["pro"], **_LONG)
    assert r.status_code == 403 and r.json()["error"]["code"] == "entitlement_exceeded"


def test_quant_long_range_queued(api: dict[str, Any]) -> None:
    r = _submit(api["client"], api["quant"], **_LONG)
    assert r.status_code == 202 and r.json()["data"]["status"] == "queued"


def test_bad_spec_422(api: dict[str, Any]) -> None:
    r = api["client"].post(
        "/api/v1/backtests", json={"spec": _spec(costs_bps=99999)}, headers=_h(api["pro"])
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


# --- submit → poll → run → idempotent --------------------------------------


def test_submit_poll_run_lifecycle(api: dict[str, Any]) -> None:
    client, pro = api["client"], api["pro"]
    bid = _submit(client, pro).json()["data"]["id"]

    poll = client.get(f"/api/v1/backtests/{bid}", headers=_h(pro)).json()["data"]
    assert poll["status"] == "queued" and poll["metrics"] is None

    run_backtest(bid)  # the worker's job (QV-065 engine → succeeded with real metrics)
    done = client.get(f"/api/v1/backtests/{bid}", headers=_h(pro)).json()["data"]
    assert done["status"] == "succeeded" and done["finished_at"] is not None
    # QV-065: the real engine populates the core metric set (not the old empty placeholder dict).
    assert {"total_return", "n_rebalances"} <= set(done["metrics"])

    run_backtest(bid)  # idempotent: a non-queued row is a no-op (still succeeded)
    assert (
        client.get(f"/api/v1/backtests/{bid}", headers=_h(pro)).json()["data"]["status"]
        == "succeeded"
    )


def test_reproducibility_persisted(api: dict[str, Any], admin_engine: Engine) -> None:
    """QV-069: the succeeded row stores the full spec + both methodology version columns, and the
    metrics carry the reproducibility fingerprint."""
    client, pro = api["client"], api["pro"]
    bid = _submit(client, pro).json()["data"]["id"]
    run_backtest(bid)

    done = client.get(f"/api/v1/backtests/{bid}", headers=_h(pro)).json()["data"]
    assert {"reproducibility_hash", "model_version", "weights_version"} <= set(done["metrics"])

    with admin_engine.connect() as conn:
        row = conn.execute(
            text("SELECT model_version, weights_version, spec FROM backtests WHERE id = :id"),
            {"id": bid},
        ).one()
    assert row.model_version and row.weights_version == "equal-weight-v1"  # columns populated
    assert (
        row.spec["rules"]["top_n"] == 20 and row.spec["start"] == "2020-01-01"
    )  # spec round-trips


def test_engine_error_marks_failed(api: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """An engine exception is captured as status='failed' + error — the task never crashes."""
    client, pro = api["client"], api["pro"]
    bid = _submit(client, pro).json()["data"]["id"]

    def _boom(_self: Any, _spec: Any) -> Any:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr("quantvista.analytics.backtest.BacktestEngine.run", _boom)
    run_backtest(bid)
    done = client.get(f"/api/v1/backtests/{bid}", headers=_h(pro)).json()["data"]
    assert done["status"] == "failed"
    assert "engine exploded" in done["error"]


def test_list_own_backtests(api: dict[str, Any]) -> None:
    client, pro = api["client"], api["pro"]
    _submit(client, pro)
    _submit(client, pro)
    items = client.get("/api/v1/backtests", headers=_h(pro)).json()["data"]
    assert len(items) == 2 and all(i["status"] == "queued" for i in items)


# --- isolation --------------------------------------------------------------


def test_cross_tenant_get_404(api: dict[str, Any]) -> None:
    client = api["client"]
    bid = _submit(client, api["pro"]).json()["data"]["id"]
    assert client.get(f"/api/v1/backtests/{bid}", headers=_h(api["other"])).status_code == 404


def test_unknown_backtest_404(api: dict[str, Any]) -> None:
    r = api["client"].get(f"/api/v1/backtests/{uuid4()}", headers=_h(api["pro"]))
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"

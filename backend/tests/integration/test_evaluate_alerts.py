"""evaluate_alerts end-to-end (QV-048) — real app + PG, two tenants. A target stock is seeded with a
score + fundamentals; rules are created via the API, then the cross-tenant evaluator runs. Covers:
matching rule fires (correct payload/tenant), non-matching doesn't, dedup (re-run → 0 new), and the
AlertsFired event via the task. Cleaned up by market/users (alert_rules/events cascade)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.alerts.services import AlertEvaluationService
from quantvista.api.app import create_app
from quantvista.core.events import get_event_bus, reset_event_bus
from quantvista.jobs.alerts import evaluate_alerts
from quantvista.market_data.fundamentals import record_fundamental_version

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
_AS_OF = date(2026, 7, 12)


def _register(client: TestClient) -> tuple[str, str]:
    email = f"qv-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    return email, token


def _rule(
    client: TestClient, token: str, target_id: UUID, metric: str, op: str, value: float
) -> str:
    body = {
        "scope": "stock",
        "target_id": str(target_id),
        "condition": {"metric": metric, "op": op, "value": value},
        "channel": "in_app",
    }
    r = client.post("/api/v1/alerts", json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201
    return str(r.json()["data"]["id"])


@dataclass
class _World:
    client: TestClient
    token_a: str
    token_b: str
    stock_id: UUID


@pytest.fixture
def world(admin_engine: Engine) -> Iterator[_World]:
    market_id, stock_id = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": f"T{uuid4().hex[:6]}"},
        )
        conn.execute(
            text(
                "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                "VALUES (:id, :m, :s, 'Co', 'IT')"
            ),
            {"id": stock_id, "m": market_id, "s": f"AL{uuid4().hex[:6]}"},
        )
        # composite_score = 40 (low → a `< 50` rule fires); pe = 100 (a `< 50` rule does NOT).
        conn.execute(
            text(
                "INSERT INTO scores (stock_id, date, composite_score, momentum_score, coverage, "
                "weights_version, model_version) "
                "VALUES (:s, :d, 40.0, 50.0, 100.0, 'v1', 'score-v1')"
            ),
            {"s": stock_id, "d": _AS_OF},
        )
        with Session(bind=conn) as session:
            record_fundamental_version(
                session,
                stock_id,
                date(2025, 12, 31),
                "annual",
                {"pe": Decimal(100)},
                knowledge_time=datetime(2026, 7, 1, tzinfo=UTC),
            )
            session.commit()

    client = TestClient(create_app(), base_url="https://testserver")
    email_a, token_a = _register(client)
    email_b, token_b = _register(client)
    yield _World(client, token_a, token_b, stock_id)

    with admin_engine.begin() as conn:
        for email in (email_a, email_b):  # deleting the tenant cascades alert_rules + alert_events
            conn.execute(
                text(
                    "DELETE FROM tenants WHERE id IN (SELECT m.tenant_id FROM memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
                ),
                {"e": email},
            )
            conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
        conn.execute(text("DELETE FROM scores WHERE stock_id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM fundamentals WHERE stock_id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM stocks WHERE id = :s"), {"s": stock_id})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})
        # the run_key is date-based → clear it so the task is re-runnable across suite runs
        conn.execute(text("DELETE FROM jobs_runs WHERE run_key LIKE 'alerts:%'"))


def _events(admin_engine: Engine, rule_id: str) -> list[dict[str, Any]]:
    with admin_engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT tenant_id, dedup_key, payload, status FROM alert_events "
                    "WHERE alert_rule_id = :r"
                ),
                {"r": rule_id},
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


def test_matching_rules_fire_and_dedup(world: _World) -> None:
    _rule(world.client, world.token_a, world.stock_id, "composite_score", "lt", 50)  # 40<50 → fires
    _rule(world.client, world.token_a, world.stock_id, "pe", "lt", 50)  # pe=100 → no fire
    _rule(world.client, world.token_b, world.stock_id, "composite_score", "lt", 50)  # fires

    fired = AlertEvaluationService().evaluate(_AS_OF, "scores")
    assert fired == 2  # both composite rules; the pe rule does not match

    again = AlertEvaluationService().evaluate(_AS_OF, "scores")
    assert again == 0  # dedup: same cycle date → no new events


def test_events_persisted_with_tenant_and_payload(world: _World, admin_engine: Engine) -> None:
    a_hit = _rule(world.client, world.token_a, world.stock_id, "composite_score", "lt", 50)
    b_hit = _rule(world.client, world.token_b, world.stock_id, "composite_score", "lt", 50)
    AlertEvaluationService().evaluate(_AS_OF, "scores")

    a_events, b_events = _events(admin_engine, a_hit), _events(admin_engine, b_hit)
    assert len(a_events) == 1 and len(b_events) == 1
    assert a_events[0]["tenant_id"] != b_events[0]["tenant_id"]  # each under its own tenant
    assert a_events[0]["dedup_key"] == _AS_OF.isoformat()
    assert a_events[0]["status"] == "pending"  # undelivered (delivery is QV-049)
    assert a_events[0]["payload"]["metric"] == "composite_score"
    assert a_events[0]["payload"]["value"] == 40.0


def test_task_runs_and_emits_alerts_fired(world: _World) -> None:
    _rule(world.client, world.token_a, world.stock_id, "composite_score", "lt", 50)
    reset_event_bus()
    fired: list[dict[str, Any]] = []
    get_event_bus().subscribe("AlertsFired", lambda e: fired.append(e["payload"]))

    assert evaluate_alerts(_AS_OF.isoformat(), "scores") == "succeeded"
    assert fired and fired[0]["trigger"] == "scores" and fired[0]["count"] >= 1

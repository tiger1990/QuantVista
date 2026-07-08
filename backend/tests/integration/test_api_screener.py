"""POST /screener end-to-end (QV-038) — real app + PG + auth. Seeds 3 scored stocks, exercises
allow-list filtering/sorting/pagination + the injection defence. Cleaned up."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.repositories import upsert_factor_values, upsert_scores
from quantvista.analytics.scoring import FactorValue, ScoreEngine
from quantvista.api.app import create_app

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"
_AS_OF = date(2026, 1, 20)


@dataclass
class _Fixture:
    client: TestClient
    token: str
    market: str


def _snapshot(pct: float) -> list[FactorValue]:
    return [
        FactorValue("pe", 10.0, -0.5, pct, pct),
        FactorValue("roe", 0.2, 0.5, pct, pct),
        FactorValue("ret_6m", 0.1, 0.3, pct, pct),
        FactorValue("beta", 1.0, 0.0, pct, pct),
    ]


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[_Fixture]:
    market_id = uuid4()
    u = uuid4().hex[:6]
    market = f"T{u}"
    ids = {"A": uuid4(), "B": uuid4(), "C": uuid4()}
    pcts = {"A": 80.0, "B": 50.0, "C": 20.0}
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": market},
        )
        for k, sid in ids.items():
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :s, 'Co', 'IT')"
                ),
                {"id": sid, "m": market_id, "s": f"{k}{u}"},
            )
        snapshot = {ids[k]: _snapshot(pcts[k]) for k in ids}
        scores = ScoreEngine().compute_scores(snapshot, _AS_OF)
        with Session(bind=conn) as session:
            upsert_factor_values(session, _AS_OF, snapshot)
            upsert_scores(session, scores)
            session.commit()

    client = TestClient(create_app(), base_url="https://testserver")
    email = f"qv-{uuid4()}@test.local"
    token = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["data"]["access_token"]
    yield _Fixture(client, token, market)

    with admin_engine.begin() as conn:
        idlist = list(ids.values())
        for tbl in ("factor_values", "scores"):
            conn.execute(text(f"DELETE FROM {tbl} WHERE stock_id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM stocks WHERE id = ANY(:i)"), {"i": idlist})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})
        conn.execute(
            text(
                "DELETE FROM tenants WHERE id IN (SELECT m.tenant_id FROM memberships m "
                "JOIN users usr ON usr.id = m.user_id WHERE usr.email = :e)"
            ),
            {"e": email},
        )
        conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


def _post(api: _Fixture, body: dict[str, object]) -> Response:
    resp: Response = api.client.post(
        "/api/v1/screener",
        json={"market": api.market, **body},
        headers={"Authorization": f"Bearer {api.token}"},
    )
    return resp


def test_filter_and_count(api: _Fixture) -> None:
    r = _post(api, {"filters": [{"field": "composite_score", "op": "gte", "value": 60}]})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["count"] == 1  # only the composite≈80 stock
    assert [row["composite_score"] >= 60 for row in body["data"]] == [True]
    assert r.headers["X-QuantVista-Disclaimer"] == "research-only; not investment advice"


def test_sort_desc_nulls_last(api: _Fixture) -> None:
    r = _post(api, {"sort": "-composite_score"})
    scores = [row["composite_score"] for row in r.json()["data"]]
    assert scores == sorted(scores, reverse=True)  # 80, 50, 20


def test_cursor_pagination(api: _Fixture) -> None:
    p1 = _post(api, {"sort": "-composite_score", "limit": 1}).json()
    assert len(p1["data"]) == 1 and p1["meta"]["count"] == 3 and p1["meta"]["next_cursor"]
    p2 = _post(
        api, {"sort": "-composite_score", "limit": 1, "cursor": p1["meta"]["next_cursor"]}
    ).json()
    assert p2["data"][0]["symbol"] != p1["data"][0]["symbol"]


def test_non_allowlist_field_is_422(api: _Fixture) -> None:
    r = _post(api, {"filters": [{"field": "id", "op": "eq", "value": "x"}]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_injection_value_is_bound_as_data(api: _Fixture) -> None:
    r = _post(
        api, {"filters": [{"field": "sector", "op": "eq", "value": "IT'; DROP TABLE stocks;--"}]}
    )
    assert r.status_code == 200  # executes safely, matches nothing
    assert r.json()["data"] == []

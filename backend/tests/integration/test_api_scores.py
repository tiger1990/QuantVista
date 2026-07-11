"""/scores/{symbol} + /decomposition + /rankings end-to-end (QV-033) — real app + PG + Redis + auth.

Seeds 3 stocks with a *consistent* score + factor_values (built via the real ScoreEngine, so the
decomposition provably sums to the persisted composite). Asserts scores, decomposition Σ==composite
with PIT as_of, ranked-desc order + the Free-tier quota surfaced. Cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
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
    top: str  # highest composite
    composites: dict[str, float]


def _snapshot(stock_id: UUID, pct: float) -> list[FactorValue]:
    # one factor per category; all percentiles = pct → composite == pct (weights re-normalize to 1)
    return [
        FactorValue("pe", 10.0, -0.5, pct, pct),  # fundamental
        FactorValue("roe", 0.2, 0.5, pct, pct),  # quality
        FactorValue("ret_6m", 0.1, 0.3, pct, pct),  # momentum
        FactorValue("beta", 1.0, 0.0, pct, pct),  # risk
    ]


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[_Fixture]:
    market_id = uuid4()
    u = uuid4().hex[:6]
    market = f"T{u}"
    syms = {"A": f"A{u}", "B": f"B{u}", "C": f"C{u}"}
    ids = {k: uuid4() for k in syms}
    pcts = {"A": 80.0, "B": 50.0, "C": 20.0}
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": market},
        )
        for k, sym in syms.items():
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector) "
                    "VALUES (:id, :m, :s, 'Co', 'IT')"
                ),
                {"id": ids[k], "m": market_id, "s": sym},
            )
        snapshot = {ids[k]: _snapshot(ids[k], pcts[k]) for k in syms}
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
    composites = {syms[k]: s.composite for k in syms for s in scores if s.stock_id == ids[k]}
    yield _Fixture(client, token, market, syms["A"], composites)

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


def _h(api: _Fixture) -> dict[str, str]:
    return {"Authorization": f"Bearer {api.token}"}


def test_score_endpoint(api: _Fixture) -> None:
    r = api.client.get(f"/api/v1/scores/{api.top}", headers=_h(api))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["symbol"] == api.top
    assert d["composite"] == pytest.approx(api.composites[api.top], abs=0.01)
    assert d["model_version"] == "score-v1"
    assert r.headers["X-QuantVista-Disclaimer"] == "research-only; not investment advice"


def test_decomposition_sums_to_composite_with_pit_dates(api: _Fixture) -> None:
    r = api.client.get(f"/api/v1/scores/{api.top}/decomposition", headers=_h(api))
    assert r.status_code == 200
    d = r.json()["data"]
    assert len(d["factors"]) == 4  # one per category
    assert all(f["as_of"] == _AS_OF.isoformat() for f in d["factors"])  # PIT date on each
    total = sum(f["contribution"] for f in d["factors"])
    assert total == pytest.approx(d["composite"], abs=0.01)  # US-02: parts sum to whole
    assert d["sum_of_contributions"] == pytest.approx(d["composite"], abs=0.01)


def test_unknown_symbol_404(api: _Fixture) -> None:
    r = api.client.get(f"/api/v1/scores/NOPE{uuid4().hex[:5]}", headers=_h(api))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_rankings_desc_order_and_free_tier(api: _Fixture) -> None:
    r = api.client.get(f"/api/v1/rankings?market={api.market}", headers=_h(api))
    assert r.status_code == 200
    body = r.json()
    syms = [i["symbol"] for i in body["data"]]
    assert syms[0] == api.top  # highest composite first
    assert [i["rank"] for i in body["data"]] == [1, 2, 3]
    assert body["data"][0]["composite_score"] >= body["data"][1]["composite_score"]
    assert "close" in body["data"][0]  # latest price field present (QV-093; null with no prices)
    assert body["meta"]["tier_limit"] == 50  # Free entitlement surfaced
    assert body["meta"]["truncated"] is False  # only 3 stocks

    capped = api.client.get(f"/api/v1/rankings?market={api.market}&limit=1", headers=_h(api))
    cbody = capped.json()
    assert len(cbody["data"]) == 1 and cbody["meta"]["truncated"] is True

"""GET /stocks + /stocks/{symbol} end-to-end (QV-032) — real FastAPI app + Postgres + auth.

Drives the app via TestClient with a real bearer token; seeds a throwaway market + 3 stocks (one
scored, with a price + fundamentals). Asserts keyset pagination, sector filter, the master+snapshot
detail + disclaimer header, 404 for unknown, 401 for unauth. Cleaned up.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from quantvista.api.app import create_app
from quantvista.market_data.fundamentals import record_fundamental_version

pytestmark = pytest.mark.integration
PASSWORD = "correct-horse-battery-staple"


@dataclass
class _Fixture:
    client: TestClient
    token: str
    market: str
    symbols: list[str]  # sorted asc
    scored: str  # the symbol with a score/price/fundamentals


@pytest.fixture
def api(admin_engine: Engine) -> Iterator[_Fixture]:
    market_id = uuid4()
    u = uuid4().hex[:6]
    market = f"T{u}"
    # symbols sort asc: A.. < B.. < C..
    syms = {"A": f"A{u}", "B": f"B{u}", "C": f"C{u}"}
    ids = {k: uuid4() for k in syms}
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": market},
        )
        for k, sym in syms.items():
            sector = "Financial Services" if k == "C" else "Information Technology"
            conn.execute(
                text(
                    "INSERT INTO stocks (id, market_id, symbol, company_name, sector, "
                    "market_cap_bucket) VALUES (:id, :m, :s, :n, :sec, 'large')"
                ),
                {"id": ids[k], "m": market_id, "s": sym, "n": f"{sym} Ltd", "sec": sector},
            )
        # A is fully scored: a score row + a price + a fundamentals filing.
        conn.execute(
            text(
                "INSERT INTO scores (stock_id, date, composite_score, momentum_score, coverage, "
                "weights_version, model_version) "
                "VALUES (:s, :d, 75.5, 60.0, 50.0, 'v1', 'score-v1')"
            ),
            {"s": ids["A"], "d": date(2026, 1, 20)},
        )
        conn.execute(
            text(
                "INSERT INTO daily_prices (stock_id, date, open, high, low, close, adj_close, "
                "volume, source) VALUES (:s, :d, 100, 102, 99, 101, 101, 1000, 'seed')"
            ),
            {"s": ids["A"], "d": date(2026, 1, 20)},
        )
        with Session(bind=conn) as session:
            record_fundamental_version(
                session,
                ids["A"],
                date(2025, 12, 31),
                "quarterly",
                {"pe": Decimal("18.5"), "roe": Decimal("0.22")},
                knowledge_time=datetime(2026, 1, 15, tzinfo=UTC),
            )
            session.commit()

    client = TestClient(create_app(), base_url="https://testserver")
    email = f"qv-{uuid4()}@test.local"
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    token = reg.json()["data"]["access_token"]
    yield _Fixture(client, token, market, sorted(syms.values()), syms["A"])

    with admin_engine.begin() as conn:
        idlist = list(ids.values())
        for tbl in ("scores", "daily_prices", "fundamentals"):
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


def _auth(api: _Fixture) -> dict[str, str]:
    return {"Authorization": f"Bearer {api.token}"}


def test_list_paginates_by_symbol(api: _Fixture) -> None:
    r1 = api.client.get(f"/api/v1/stocks?market={api.market}&limit=2", headers=_auth(api))
    assert r1.status_code == 200
    body1 = r1.json()
    assert [i["symbol"] for i in body1["data"]] == api.symbols[:2]
    assert body1["meta"]["next_cursor"] is not None
    assert body1["meta"]["disclaimer"]
    assert r1.headers["X-QuantVista-Disclaimer"] == "research-only; not investment advice"

    r2 = api.client.get(
        f"/api/v1/stocks?market={api.market}&limit=2&cursor={body1['meta']['next_cursor']}",
        headers=_auth(api),
    )
    body2 = r2.json()
    assert [i["symbol"] for i in body2["data"]] == api.symbols[2:]  # no overlap
    assert body2["meta"]["next_cursor"] is None  # last page


def test_list_filters_by_sector_and_shows_score(api: _Fixture) -> None:
    r = api.client.get(
        f"/api/v1/stocks?market={api.market}&sector=Financial Services", headers=_auth(api)
    )
    data = r.json()["data"]
    assert [i["symbol"] for i in data] == [api.symbols[2]]  # only C is Financial Services
    scored = api.client.get(
        f"/api/v1/stocks?market={api.market}&sector=Information Technology", headers=_auth(api)
    ).json()["data"]
    a_row = next(i for i in scored if i["symbol"] == api.scored)
    assert a_row["composite_score"] == 75.5  # latest score surfaced in the list
    assert a_row["close"] == 101.0  # latest close price surfaced in the list (QV-093)


def test_detail_returns_master_and_snapshot(api: _Fixture) -> None:
    r = api.client.get(f"/api/v1/stocks/{api.scored}", headers=_auth(api))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["symbol"] == api.scored and d["is_active"] is True
    snap = d["snapshot"]
    assert snap["composite_score"] == 75.5
    assert snap["close"] == 101.0
    assert snap["pe"] == 18.5
    assert r.headers["X-QuantVista-Disclaimer"] == "research-only; not investment advice"
    assert r.json()["meta"]["disclaimer"]
    # a 2nd call returns identical data (cache-served or DB — both correct)
    assert api.client.get(f"/api/v1/stocks/{api.scored}", headers=_auth(api)).json()["data"] == d


def test_unknown_symbol_is_404(api: _Fixture) -> None:
    r = api.client.get(f"/api/v1/stocks/NOPE{uuid4().hex[:6]}", headers=_auth(api))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_requires_auth(api: _Fixture) -> None:
    assert api.client.get(f"/api/v1/stocks?market={api.market}").status_code == 401

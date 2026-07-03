"""Universe sync — master upsert + PIT constituents reconcile (QV-019); real PG, fake provider.

Uses a throwaway market + unique index_code so nothing touches the seeded reference universe. The
fake provider lets us script add / drop / reconstitution / unresolved scenarios deterministically.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.jobs import universe as universe_mod
from quantvista.jobs.universe import (
    UniverseSyncError,
    sync_index_constituents,
    sync_index_constituents_now,
    sync_stock_master,
)
from quantvista.market_data.models import (
    CorporateAction,
    FundamentalSnapshot,
    LicenseClass,
    PriceBar,
    Provenance,
    ShareholdingSnapshot,
    UniverseEntry,
)
from quantvista.market_data.services import UniverseSyncService

pytestmark = pytest.mark.integration

_PROV = Provenance("yfinance", None, LicenseClass.NON_COMMERCIAL_DEV)
_SEED_FROM = date(2024, 1, 1)
_AS_OF = date(2026, 6, 1)


def _entry(symbol: str, weight: str | None = None) -> UniverseEntry:
    return UniverseEntry(
        symbol=symbol,
        name=f"{symbol} Company",
        isin=None,
        exchange="NSE",
        is_active=True,
        provenance=_PROV,
        weight=Decimal(weight) if weight is not None else None,
    )


class _FakeProvider:
    def __init__(self, entries: Sequence[UniverseEntry]) -> None:
        self._entries = list(entries)

    def list_universe(self, index_code: str = "NIFTY200") -> Sequence[UniverseEntry]:
        return self._entries

    def get_prices(
        self, symbol: str, start: date, end: date, interval: str = "1d"
    ) -> Sequence[PriceBar]:
        return []

    def get_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        return []

    def get_fundamentals(self, symbol: str) -> Sequence[FundamentalSnapshot]:
        return []

    def get_shareholding(self, symbol: str) -> Sequence[ShareholdingSnapshot]:
        return []


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object]]] = []

    def publish(self, topic: str, event: dict[str, object]) -> None:
        self.published.append((topic, event))

    def subscribe(self, topic: str, handler: object) -> None: ...

    def topics(self) -> set[str]:
        return {t for t, _ in self.published}


@dataclass
class _Env:
    market: str
    market_id: UUID
    index_code: str


@pytest.fixture
def env(admin_engine: Engine) -> Iterator[_Env]:
    market_id = uuid4()
    market = f"T{uuid4().hex[:6]}"
    index_code = f"TESTIDX_{uuid4().hex[:8]}"
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO markets (id, code, name, country, currency, timezone) "
                "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
            ),
            {"id": market_id, "c": market},
        )
    yield _Env(market, market_id, index_code)
    with admin_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM index_constituents WHERE index_code = :ic"), {"ic": index_code}
        )
        conn.execute(text("DELETE FROM stocks WHERE market_id = :m"), {"m": market_id})
        conn.execute(text("DELETE FROM markets WHERE id = :m"), {"m": market_id})
        conn.execute(
            text("DELETE FROM jobs_runs WHERE run_key LIKE :k OR run_key LIKE :m"),
            {"k": f"constituents:{index_code}%", "m": f"master:{market}%"},
        )


def _stock_id(admin_engine: Engine, env: _Env, symbol: str) -> UUID:
    with admin_engine.connect() as conn:
        return cast(
            UUID,
            conn.execute(
                text("SELECT id FROM stocks WHERE market_id = :m AND symbol = :s"),
                {"m": env.market_id, "s": symbol},
            ).scalar_one(),
        )


def _open_symbols(admin_engine: Engine, env: _Env) -> set[str]:
    with admin_engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT s.symbol FROM index_constituents ic "
                    "JOIN stocks s ON s.id = ic.stock_id "
                    "WHERE ic.index_code = :ic AND ic.effective_to IS NULL"
                ),
                {"ic": env.index_code},
            )
        }


def _seed_open_members(admin_engine: Engine, env: _Env, symbols: list[str]) -> None:
    with admin_engine.begin() as conn:
        for sym in symbols:
            conn.execute(
                text(
                    "INSERT INTO index_constituents (index_code, stock_id, effective_from) "
                    "VALUES (:ic, :sid, :ef)"
                ),
                {"ic": env.index_code, "sid": _stock_id(admin_engine, env, sym), "ef": _SEED_FROM},
            )


# --- sync_stock_master --------------------------------------------------------
def test_master_inserts_then_updates_idempotently(admin_engine: Engine, env: _Env) -> None:
    bus = _FakeBus()
    svc = UniverseSyncService(_FakeProvider([_entry("AAA"), _entry("BBB")]), bus)

    first = svc.sync_stock_master(env.market, index_code=env.index_code)
    assert (first.inserted, first.updated) == (2, 0)
    assert bus.topics() == {"StockMasterUpdated"}

    second = svc.sync_stock_master(env.market, index_code=env.index_code)
    assert (second.inserted, second.updated) == (0, 2)  # same rows, upserted in place
    with admin_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM stocks WHERE market_id = :m"), {"m": env.market_id}
        ).scalar_one()
    assert n == 2


# --- sync_index_constituents: PIT reconcile -----------------------------------
def test_reconstitution_opens_adds_closes_drops_keeps_history(
    admin_engine: Engine, env: _Env
) -> None:
    # Master brings A,B,C,D into the catalogue; seed open membership A,B,C at the old date.
    provider_all = [_entry(s) for s in ("A", "B", "C", "D")]
    UniverseSyncService(_FakeProvider(provider_all), _FakeBus()).sync_stock_master(
        env.market, index_code=env.index_code
    )
    _seed_open_members(admin_engine, env, ["A", "B", "C"])

    # Reconstitution: index becomes {B, C, D} with weights.
    bus = _FakeBus()
    new_set = [_entry("B", "0.4"), _entry("C", "0.35"), _entry("D", "0.25")]
    report = UniverseSyncService(_FakeProvider(new_set), bus).sync_index_constituents(
        env.index_code, env.market, _AS_OF
    )
    assert (report.added, report.closed, report.unchanged) == (1, 1, 2)  # +D, -A, B/C
    assert bus.topics() == {"ConstituentsUpdated"}
    assert _open_symbols(admin_engine, env) == {"B", "C", "D"}

    with admin_engine.connect() as conn:
        # A is closed (survivorship-free — row retained with effective_to = as_of).
        a_to = conn.execute(
            text(
                "SELECT effective_to FROM index_constituents ic "
                "JOIN stocks s ON s.id = ic.stock_id "
                "WHERE ic.index_code = :ic AND s.symbol = 'A'"
            ),
            {"ic": env.index_code},
        ).scalar_one()
        assert a_to == _AS_OF
        # D opened at as_of; weight written.
        d = conn.execute(
            text(
                "SELECT effective_from, effective_to, weight FROM index_constituents ic "
                "JOIN stocks s ON s.id = ic.stock_id WHERE ic.index_code = :ic AND s.symbol = 'D'"
            ),
            {"ic": env.index_code},
        ).one()
        assert (
            d.effective_from == _AS_OF
            and d.effective_to is None
            and d.weight == Decimal("0.250000")
        )


def _xmin(admin_engine: Engine, env: _Env, symbol: str) -> int:
    """Postgres system column bumped on every physical row write — proves a no-op update."""
    with admin_engine.connect() as conn:
        return cast(
            int,
            conn.execute(
                text(
                    "SELECT ic.xmin::text::bigint FROM index_constituents ic "
                    "JOIN stocks s ON s.id = ic.stock_id "
                    "WHERE ic.index_code = :ic AND s.symbol = :s AND ic.effective_to IS NULL"
                ),
                {"ic": env.index_code, "s": symbol},
            ).scalar_one(),
        )


def test_reconcile_is_idempotent_and_weight_update_is_a_true_no_op(
    admin_engine: Engine, env: _Env
) -> None:
    UniverseSyncService(_FakeProvider([_entry("A"), _entry("B")]), _FakeBus()).sync_stock_master(
        env.market, index_code=env.index_code
    )
    _seed_open_members(admin_engine, env, ["A", "B"])
    svc = UniverseSyncService(_FakeProvider([_entry("A", "0.6"), _entry("B", "0.4")]), _FakeBus())
    svc.sync_index_constituents(
        env.index_code, env.market, _AS_OF
    )  # writes weights (NULL → 0.6/0.4)
    xmin_before = _xmin(admin_engine, env, "A")

    again = svc.sync_index_constituents(
        env.index_code, env.market, _AS_OF
    )  # identical set + weights
    assert (again.added, again.closed) == (0, 0)
    assert _open_symbols(admin_engine, env) == {"A", "B"}
    # The IS DISTINCT FROM guard means the second run does not rewrite the unchanged row.
    assert _xmin(admin_engine, env, "A") == xmin_before


def test_unresolved_member_aborts_and_mutates_nothing(admin_engine: Engine, env: _Env) -> None:
    # Only A,B exist; provider says {A,B,C} — C has no stock row → abort, nothing closed/opened.
    UniverseSyncService(_FakeProvider([_entry("A"), _entry("B")]), _FakeBus()).sync_stock_master(
        env.market, index_code=env.index_code
    )
    _seed_open_members(admin_engine, env, ["A", "B"])
    bus = _FakeBus()
    report = UniverseSyncService(
        _FakeProvider([_entry("A"), _entry("B"), _entry("C")]), bus
    ).sync_index_constituents(env.index_code, env.market, _AS_OF)
    assert report.unresolved == ["C"] and (report.added, report.closed) == (0, 0)
    assert bus.topics() == set()  # no ConstituentsUpdated — nothing happened
    assert _open_symbols(admin_engine, env) == {"A", "B"}  # untouched


# --- job wiring (run_job + strict policy), fake provider monkeypatched ---------
def test_constituents_task_fails_run_on_unresolved(
    admin_engine: Engine, env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    UniverseSyncService(_FakeProvider([_entry("A")]), _FakeBus()).sync_stock_master(
        env.market, index_code=env.index_code
    )
    _seed_open_members(admin_engine, env, ["A"])
    # Provider claims {A, ZZZ}; ZZZ unresolved → the run_job wrapper marks the run failed.
    monkeypatch.setattr(
        universe_mod, "YFinanceDevProvider", lambda: _FakeProvider([_entry("A"), _entry("ZZZ")])
    )
    with pytest.raises(UniverseSyncError):
        sync_index_constituents_now(env.index_code, env.market, as_of=_AS_OF)
    with admin_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM jobs_runs WHERE run_key = :k"),
            {"k": f"constituents:{env.index_code}:{_AS_OF.isoformat()}"},
        ).scalar_one()
    assert status == "failed"


def test_constituents_task_succeeds_via_run_job(
    admin_engine: Engine, env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    UniverseSyncService(_FakeProvider([_entry("A"), _entry("B")]), _FakeBus()).sync_stock_master(
        env.market, index_code=env.index_code
    )
    _seed_open_members(admin_engine, env, ["A"])  # B will be added
    monkeypatch.setattr(
        universe_mod, "YFinanceDevProvider", lambda: _FakeProvider([_entry("A"), _entry("B")])
    )
    outcome = sync_index_constituents_now(env.index_code, env.market, as_of=_AS_OF)
    assert outcome.status.value == "succeeded"
    assert _open_symbols(admin_engine, env) == {"A", "B"}


def test_master_celery_task_records_run(
    admin_engine: Engine, env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        universe_mod, "YFinanceDevProvider", lambda: _FakeProvider([_entry("AAA"), _entry("BBB")])
    )
    result = sync_stock_master.apply(args=[env.market, env.index_code])
    assert result.get() == "succeeded"
    with admin_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM stocks WHERE market_id = :m"), {"m": env.market_id}
        ).scalar_one()
    assert n == 2


def test_constituents_celery_task_reconciles(
    admin_engine: Engine, env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    UniverseSyncService(_FakeProvider([_entry("A"), _entry("B")]), _FakeBus()).sync_stock_master(
        env.market, index_code=env.index_code
    )
    _seed_open_members(admin_engine, env, ["A"])  # B added by the reconcile
    monkeypatch.setattr(
        universe_mod, "YFinanceDevProvider", lambda: _FakeProvider([_entry("A"), _entry("B")])
    )
    result = sync_index_constituents.apply(args=[env.index_code, env.market, _AS_OF.isoformat()])
    assert result.get() == "succeeded"
    assert _open_symbols(admin_engine, env) == {"A", "B"}

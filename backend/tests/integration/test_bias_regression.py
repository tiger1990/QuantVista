"""Backtest bias-regression guards (QV-066) — permanent, CI-required, non-skippable.

Two counterfactual fixtures that drive the **whole** ``BacktestEngine`` over synthetic data and
**fail iff** the engine commits either cardinal sin (05 §4, 08 §5):

1. **Look-ahead** — a backtest ending at ``EARLY`` is byte-identical with/without a post-``EARLY``
   trap (future data invisible); the same trap *changes* a backtest ending at ``LATE`` (it becomes
   knowable at a post-trap rebalance → the guard has teeth).
2. **Survivorship** — a high-ranked name that delists mid-run is included while it was a member and
   force-exited at last price; running through the real survivorship-free seam vs the existing
   ``active_universe`` (current-members-only) reader yields *different* metrics.

Hermetic: the engine's hard-coded ``universe_as_of(index_code="NIFTY200", market="NSE")`` is
redirected to a synthetic seeded index via a thin adapter over the **real** ``BacktestDataAccess`` —
every other read (``ranked_universe``/``price_panel``/``last_price_as_of``) hits real PIT code.
Rolled-back seed, no residue. Runs in the required ``backend-rls`` gate (``pytest -m bias``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from quantvista.analytics.backtest import BacktestData, BacktestEngine, BacktestResult
from quantvista.analytics.backtest_data import BacktestDataAccess
from quantvista.market_data.fundamentals import record_fundamental_version
from quantvista.market_data.repositories import active_universe, historical_universe
from quantvista.market_data.trading_calendar import sessions_in_range
from quantvista.schemas.backtest import BacktestSpec

pytestmark = [pytest.mark.integration, pytest.mark.bias]

START = date(2024, 1, 1)
EARLY = date(2024, 3, 31)
TRAP_DATE = date(2024, 4, 15)  # EARLY < TRAP_DATE < LATE; a post-trap rebalance falls in May
LATE = date(2024, 6, 30)
DELIST = date(2024, 3, 15)  # a held name delists here
_BASE_IND = date(2023, 12, 1)  # baseline indicators, knowable before START
_PERIOD = date(2023, 12, 31)
_PRE_KT = datetime(2023, 12, 5, tzinfo=UTC)
_TRAP_KT = datetime(2024, 4, 15, tzinfo=UTC)
_SESSIONS = sessions_in_range(START, LATE)


# --- redirect seams ----------------------------------------------------------


class _SyntheticSeam:
    """Real ``BacktestDataAccess`` with ``universe_as_of`` redirected to a synthetic index; spies
    the forced-exit ``last_price_as_of`` calls."""

    def __init__(self, session: Session, index_code: str, market: str) -> None:
        self._sess = session
        self._d = BacktestDataAccess(session)
        self._index, self._market = index_code, market
        self.last_price_calls: list[UUID] = []

    def universe_as_of(
        self, as_of: date, *, index_code: str = "NIFTY200", market: str = "NSE"
    ) -> list[UUID]:
        return self._d.universe_as_of(as_of, index_code=self._index, market=self._market)

    def ranked_universe(
        self, as_of: date, universe: Sequence[UUID], *, rank_by: str = "composite", top_n: int
    ) -> list[UUID]:
        return self._d.ranked_universe(as_of, universe, rank_by=rank_by, top_n=top_n)

    def basket_ids(self, symbols: Sequence[str], *, market: str = "NSE") -> list[UUID]:
        """Delegated for protocol completeness — these guards exercise the ranked path only."""
        return self._d.basket_ids(symbols, market=self._market)

    def price_panel(
        self, start: date, end: date, stock_ids: Sequence[UUID]
    ) -> dict[UUID, dict[date, Decimal]]:
        return self._d.price_panel(start, end, stock_ids)

    def last_price_as_of(
        self, as_of: date, stock_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[date, Decimal]]:
        self.last_price_calls.extend(stock_ids)
        return self._d.last_price_as_of(as_of, stock_ids)


class _BiasedSeam(_SyntheticSeam):
    """The *wrong* engine: survivorship-biased ``universe_as_of`` = current open members only
    (the existing ``active_universe`` reader), applied to every historical date."""

    def universe_as_of(
        self, as_of: date, *, index_code: str = "NIFTY200", market: str = "NSE"
    ) -> list[UUID]:
        return [u.stock_id for u in active_universe(self._sess, self._index, self._market)]


# --- seeding helpers ---------------------------------------------------------


def _market(conn: Connection) -> tuple[UUID, str]:
    mid, code = uuid4(), f"BT{uuid4().hex[:6]}"
    conn.execute(
        text(
            "INSERT INTO markets (id, code, name, country, currency, timezone) "
            "VALUES (:id, :c, 'Test', 'IN', 'INR', 'Asia/Kolkata')"
        ),
        {"id": mid, "c": code},
    )
    return mid, code


def _stock(conn: Connection, mid: UUID, *, delisted_on: date | None = None) -> UUID:
    sid = uuid4()
    conn.execute(
        text(
            "INSERT INTO stocks "
            "(id, market_id, symbol, company_name, sector, delisted_on, is_active) "
            "VALUES (:id, :m, :s, 'Co', 'IT', :d, :a)"
        ),
        {
            "id": sid,
            "m": mid,
            "s": f"BT{uuid4().hex[:6]}",
            "d": delisted_on,
            "a": delisted_on is None,
        },
    )
    return sid


def _member(conn: Connection, index: str, sid: UUID, ef: date, et: date | None) -> None:
    conn.execute(
        text(
            "INSERT INTO index_constituents "
            "(id, index_code, stock_id, effective_from, effective_to, weight) "
            "VALUES (gen_random_uuid(), :i, :s, :ef, :et, 0.5)"
        ),
        {"i": index, "s": sid, "ef": ef, "et": et},
    )


def _indicator(conn: Connection, sid: UUID, on: date, ret_6m: str) -> None:
    conn.execute(
        text(
            "INSERT INTO technical_indicators (stock_id, date, ret_6m, beta_1y) "
            "VALUES (:s, :d, :r, '1.0')"
        ),
        {"s": sid, "d": on, "r": Decimal(ret_6m)},
    )


def _fundamental(session: Session, sid: UUID, pe: str, kt: datetime) -> None:
    record_fundamental_version(
        session, sid, _PERIOD, "quarterly", {"pe": Decimal(pe)}, knowledge_time=kt
    )


def _prices(
    conn: Connection, sid: UUID, price_fn: Callable[[int], Decimal], *, until: date
) -> None:
    rows = [{"s": sid, "d": d, "c": price_fn(k)} for k, d in enumerate(_SESSIONS) if d <= until]
    conn.execute(
        text(
            "INSERT INTO daily_prices "
            "(stock_id, date, close, adj_close, high, low, volume, source) "
            "VALUES (:s, :d, :c, :c, :c, :c, 100, 'seed')"
        ),
        rows,
    )


def _run(
    session: Session,
    index: str,
    market: str,
    end: date,
    seam_cls: type[_SyntheticSeam] = _SyntheticSeam,
) -> BacktestResult:
    spec = BacktestSpec.model_validate(
        {
            "rules": {"rank_by": "momentum", "top_n": 1, "rebalance": "monthly"},
            "start": START.isoformat(),
            "end": end.isoformat(),
        }
    )
    seam: BacktestData = seam_cls(session, index, market)
    return BacktestEngine(seam).run(spec)


# --- look-ahead fixture: A(top) B C ; trap lifts C after EARLY ----------------


@dataclass(frozen=True)
class Leak:
    session: Session
    index: str
    market: str
    a: UUID
    c: UUID


@pytest.fixture
def leak(admin_engine: Engine) -> Iterator[Leak]:
    with admin_engine.connect() as conn:
        trans = conn.begin()
        try:
            mid, mcode = _market(conn)
            index = f"BTX{uuid4().hex[:6]}"
            a, b, c = _stock(conn, mid), _stock(conn, mid), _stock(conn, mid)
            for sid in (a, b, c):
                _member(conn, index, sid, date(2023, 12, 1), None)
            _indicator(conn, a, _BASE_IND, "0.30")  # A ranks top at baseline
            _indicator(conn, b, _BASE_IND, "0.20")
            _indicator(conn, c, _BASE_IND, "0.10")
            with Session(bind=conn) as s:
                for sid, pe in ((a, "10"), (b, "15"), (c, "20")):
                    _fundamental(s, sid, pe, _PRE_KT)
                s.commit()
            _prices(conn, a, lambda k: Decimal(100 + k), until=LATE)
            _prices(conn, b, lambda k: Decimal(80 + k), until=LATE)
            _prices(conn, c, lambda k: Decimal(60 + 3 * k), until=LATE)  # steep → distinct path
            with Session(bind=conn) as session:
                yield Leak(session, index, mcode, a, c)
        finally:
            trans.rollback()


def _inject_trap(session: Session, c: UUID) -> None:
    """Post-EARLY data that would lift C to the top — invisible before it is knowable."""
    conn = session.connection()
    _indicator(conn, c, TRAP_DATE, "0.99")  # future-dated momentum spike
    conn.execute(  # a post-EARLY price spike (upsert — the session bar is already seeded)
        text(
            "INSERT INTO daily_prices "
            "(stock_id, date, close, adj_close, high, low, volume, source) "
            "VALUES (:s, :d, '999', '999', '999', '999', 100, 'trap') "
            "ON CONFLICT (stock_id, date) DO UPDATE SET adj_close = EXCLUDED.adj_close"
        ),
        {"s": c, "d": TRAP_DATE},
    )
    _fundamental(session, c, "1", _TRAP_KT)  # later-knowledge restatement
    session.commit()


def test_no_lookahead_at_early(leak: Leak) -> None:
    before = _run(leak.session, leak.index, leak.market, EARLY)
    _inject_trap(leak.session, leak.c)
    after = _run(leak.session, leak.index, leak.market, EARLY)
    assert before.metrics == after.metrics  # trap is in the future → invisible → no leak


def test_trap_has_teeth_at_late(leak: Leak) -> None:
    before = _run(leak.session, leak.index, leak.market, LATE)
    _inject_trap(leak.session, leak.c)
    after = _run(leak.session, leak.index, leak.market, LATE)
    assert before.metrics != after.metrics  # knowable at a post-trap rebalance → ranking moves


# --- survivorship fixture: D(top, delists) E F --------------------------------


@dataclass(frozen=True)
class Surv:
    session: Session
    index: str
    market: str
    d: UUID
    e: UUID


@pytest.fixture
def surv(admin_engine: Engine) -> Iterator[Surv]:
    with admin_engine.connect() as conn:
        trans = conn.begin()
        try:
            mid, mcode = _market(conn)
            index = f"BTX{uuid4().hex[:6]}"
            d = _stock(conn, mid, delisted_on=DELIST)  # high-ranked, delists mid-run
            e, f = _stock(conn, mid), _stock(conn, mid)
            _member(
                conn, index, d, date(2023, 12, 1), DELIST
            )  # closed membership (survivorship-free)
            _member(conn, index, e, date(2023, 12, 1), None)
            _member(conn, index, f, date(2023, 12, 1), None)
            _indicator(conn, d, _BASE_IND, "0.90")  # D ranks top while it exists
            _indicator(conn, e, _BASE_IND, "0.50")
            _indicator(conn, f, _BASE_IND, "0.30")
            with Session(bind=conn) as s:
                for sid, pe in ((d, "10"), (e, "15"), (f, "20")):
                    _fundamental(s, sid, pe, _PRE_KT)
                s.commit()
            _prices(conn, d, lambda k: Decimal(100 + k), until=DELIST)  # truncated at delisting
            _prices(conn, e, lambda k: Decimal(60 + 2 * k), until=LATE)  # distinct path
            _prices(conn, f, lambda k: Decimal(40 + k), until=LATE)
            with Session(bind=conn) as session:
                yield Surv(session, index, mcode, d, e)
        finally:
            trans.rollback()


def test_survivorship_free_differs_from_biased(surv: Surv) -> None:
    free = _run(surv.session, surv.index, surv.market, LATE, _SyntheticSeam)
    biased = _run(surv.session, surv.index, surv.market, LATE, _BiasedSeam)
    # The biased (current-members-only) engine never holds the delisted top name → different result.
    assert free.metrics != biased.metrics


def test_universe_read_includes_delisted_but_biased_excludes(surv: Surv) -> None:
    pre = date(2024, 2, 1)  # before the delisting
    survivorship_free = set(historical_universe(surv.session, surv.index, surv.market, pre))
    biased = {u.stock_id for u in active_universe(surv.session, surv.index, surv.market)}
    assert surv.d in survivorship_free  # a member at `pre`, even though later delisted
    assert surv.d not in biased  # the current-members-only read drops it (the bias)


def test_delisted_name_force_exited(surv: Surv) -> None:
    seam = _SyntheticSeam(surv.session, surv.index, surv.market)
    spec = BacktestSpec.model_validate(
        {
            "rules": {"rank_by": "momentum", "top_n": 1, "rebalance": "monthly"},
            "start": START.isoformat(),
            "end": LATE.isoformat(),
        }
    )
    BacktestEngine(seam).run(spec)
    assert surv.d in seam.last_price_calls  # held, then force-exited at last valid price (QV-064)

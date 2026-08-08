"""Shared pytest fixtures.

Integration tests (marked ``@pytest.mark.integration``) need a reachable PostgreSQL.
They are skipped automatically when no database is reachable, so the DB-free unit
suite (and the existing CI unit job) stay green. CI's RLS job provides Postgres and
the non-superuser app role, so the integration tests run there.
"""

from __future__ import annotations

import functools
import os
import uuid as _uuid
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from quantvista.core.config import get_settings
from quantvista.core.db import app_engine, privileged_engine
from tests import db_provision


@functools.cache
def _postgres_reachable() -> bool:
    try:
        engine = create_engine(
            get_settings().admin_database_url, connect_args={"connect_timeout": 2}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


# Set by pytest_configure when this run owns a private database; read by teardown and by the
# fallback advisory lock (which is only needed when we are SHARING a database).
_RUN_DATABASE: str | None = None
_RUN_ADMIN_URL: str | None = None


def _rebind_to(database: str) -> None:
    """Point every connection this process will open at ``database``.

    Both engine factories are ``@lru_cache``d (``core/db.py``) and ``get_settings`` is too, so
    swapping the env vars alone is not enough -- a cached engine would keep talking to the old
    database. Clearing all three is the whole trick, and forgetting one fails silently.
    """
    settings = get_settings()
    os.environ["ADMIN_DATABASE_URL"] = db_provision.with_database(
        settings.admin_database_url, database
    )
    os.environ["DATABASE_URL"] = db_provision.with_database(settings.database_url, database)
    get_settings.cache_clear()
    app_engine.cache_clear()
    privileged_engine.cache_clear()


def pytest_configure(config: pytest.Config) -> None:
    """Give this run its own database, so nothing it does can touch shared state.

    Falls back to the shared database (guarded by the advisory lock below) when provisioning is
    unavailable -- no CREATE DATABASE privilege, an old server, or QV_TEST_SHARED_DB=1. The suite
    must still run in a constrained environment; it just loses the isolation.
    """
    global _RUN_DATABASE, _RUN_ADMIN_URL
    if os.environ.get("QV_TEST_SHARED_DB") == "1" or not _postgres_reachable():
        return

    admin_url = get_settings().admin_database_url
    worker = getattr(config, "workerinput", {}).get("workerid", "main")  # xdist gives each its own
    run_id = f"{worker}_{_uuid.uuid4().hex[:8]}"
    try:
        database = db_provision.create_run_database(admin_url, run_id)
    except Exception as exc:  # noqa: BLE001 -- degrade to the shared database, do not abort
        print(f"\n[conftest] per-run database unavailable ({exc}); using the shared one")
        return

    _RUN_ADMIN_URL, _RUN_DATABASE = admin_url, database
    _rebind_to(database)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Drop this run's database. Nothing to tidy inside it -- the whole thing goes."""
    if _RUN_DATABASE is None or _RUN_ADMIN_URL is None:
        return
    app_engine.cache_clear()
    privileged_engine.cache_clear()
    db_provision.drop_database(_RUN_ADMIN_URL, _RUN_DATABASE)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _postgres_reachable():
        return
    skip = pytest.mark.skip(
        reason="needs a reachable PostgreSQL (start local PG or set ADMIN_DATABASE_URL)"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    """Privileged (superuser) engine for seeding test data that bypasses RLS."""
    engine = create_engine(get_settings().admin_database_url, future=True)
    yield engine
    engine.dispose()


# Arbitrary but fixed key ("QV_I" as an int) identifying THIS suite's advisory lock.
_SUITE_LOCK_KEY = 0x51565F49


@pytest.fixture(scope="session", autouse=True)
def _serialise_suite_runs(request: pytest.FixtureRequest, admin_engine: Engine) -> Iterator[None]:
    """Hold a session-level advisory lock for the whole run, so two suites cannot interleave.

    The integration suite mutates GLOBAL state -- it creates and drops partitions of
    ``daily_prices``, and seeds/deletes rows in shared reference tables. Against a private CI
    database that is fine, and this lock is uncontended. Against the SHARED dev database it is not:
    ``CREATE TABLE ... PARTITION OF`` needs a ShareRowExclusiveLock on the parent while another
    run's INSERT holds a RowExclusiveLock on it, and the two deadlock outright. That surfaced on
    2026-08-08 as sporadic DeadlockDetected in test_daily_prices_schema / test_bias_regression --
    failures that vanished the moment the suite ran alone.

    Serialising is the honest fix: a second run WAITS instead of corrupting the first. Real
    per-run isolation (a database or schema per run) would be better still, but it is a much
    larger change and this closes the actual failure mode.
    """
    # Only needed when SHARING a database. With a per-run database (the normal path) nothing is
    # shared, so there is nothing to serialise -- this is the fallback for constrained
    # environments. Two further cases must not lock:
    #   * no database at all -- the unit-only CI job; connecting there errors the whole run.
    #   * a database, but only unit tests selected -- locking would make `pytest tests/unit`
    #     block behind someone else's long integration run for no reason.
    selected_integration = any("integration" in item.keywords for item in request.session.items)
    if _RUN_DATABASE is not None or not selected_integration or not _postgres_reachable():
        yield
        return

    conn = admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        got = conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": _SUITE_LOCK_KEY}
        ).scalar_one()
        if not got:  # another suite is mid-run -- block rather than race it
            print("\n[conftest] another test suite holds the DB lock; waiting for it to finish...")
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _SUITE_LOCK_KEY})
        yield
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _SUITE_LOCK_KEY})
        conn.close()


@pytest.fixture
def two_tenants(admin_engine: Engine) -> Iterator[dict[str, UUID]]:
    """Seed two tenants (A, B), a shared user, and one watchlist each (admin-seeded,
    bypassing RLS). Torn down via tenant cascade afterwards."""
    a, b, user = uuid4(), uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:a, 'RLS-Test-A'), (:b, 'RLS-Test-B')"),
            {"a": a, "b": b},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, email, status, mfa_enabled, created_at, updated_at) "
                "VALUES (:u, :e, 'active', false, now(), now())"
            ),
            {"u": user, "e": f"rls-{user}@test.local"},
        )
        conn.execute(
            text(
                "INSERT INTO watchlists (id, tenant_id, user_id, name, created_at) VALUES "
                "(gen_random_uuid(), :a, :u, 'A-list', now()), "
                "(gen_random_uuid(), :b, :u, 'B-list', now())"
            ),
            {"a": a, "b": b, "u": user},
        )
    yield {"a": a, "b": b, "user": user}
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), {"a": a, "b": b})
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})

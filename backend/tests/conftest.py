"""Shared pytest fixtures.

Integration tests (marked ``@pytest.mark.integration``) need a reachable PostgreSQL.
They are skipped automatically when no database is reachable, so the DB-free unit
suite (and the existing CI unit job) stay green. CI's RLS job provides Postgres and
the non-superuser app role, so the integration tests run there.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from quantvista.core.config import get_settings


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

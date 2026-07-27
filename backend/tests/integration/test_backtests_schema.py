"""backtests schema VERIFY (QV-062) — the table is forward-declared in 0011 (NO new migration).

Confirms the column set, the status CHECK, and RLS tenant isolation on the ``backtests`` table.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from quantvista.core.db import session_scope

pytestmark = pytest.mark.integration

_EXPECTED_COLUMNS = {
    "id",
    "tenant_id",
    "user_id",
    "spec",
    "status",
    "started_at",
    "finished_at",
    "result_ref",
    "metrics",
    "model_version",
    "weights_version",
    "error",
    "created_at",
}


def test_backtests_columns(admin_engine: Engine) -> None:
    with admin_engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'backtests'"
                )
            )
        }
    assert cols >= _EXPECTED_COLUMNS


def test_status_check_rejects_bad_status(
    two_tenants: dict[str, UUID], admin_engine: Engine
) -> None:
    a, user = two_tenants["a"], two_tenants["user"]
    # CHECK (status IN queued|running|succeeded|failed) → violation raises.
    with pytest.raises(DBAPIError), admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO backtests (tenant_id, user_id, spec, status) "
                "VALUES (:t, :u, '{}'::jsonb, 'bogus')"
            ),
            {"t": a, "u": user},
        )


def test_rls_isolation(two_tenants: dict[str, UUID], admin_engine: Engine) -> None:
    a, b, user = two_tenants["a"], two_tenants["b"], two_tenants["user"]
    with admin_engine.begin() as conn:  # seed A's backtest (superuser bypasses RLS)
        conn.execute(
            text(
                "INSERT INTO backtests (tenant_id, user_id, spec, status) "
                "VALUES (:t, :u, '{}'::jsonb, 'queued')"
            ),
            {"t": a, "u": user},
        )
    with session_scope(b) as s:  # B's non-superuser session sees none of A's
        assert s.execute(text("SELECT count(*) FROM backtests")).scalar_one() == 0
    with session_scope(a) as s:  # A sees its own
        assert s.execute(text("SELECT count(*) FROM backtests")).scalar_one() == 1

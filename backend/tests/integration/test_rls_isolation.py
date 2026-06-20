"""Cross-tenant isolation tests — the mandatory RLS denial gate (QV-004 AC #4).

Runs as the NON-superuser app role via ``quantvista.core.db.session_scope`` against a
real PostgreSQL. Proves tenant A cannot see or modify tenant B's data, and that an
unbound session sees nothing. (A superuser/BYPASSRLS connection would pass these
falsely — CI runs them as the app role.)
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import CursorResult, text
from sqlalchemy.orm import Session

from quantvista.core.db import session_scope

pytestmark = pytest.mark.integration


def _watchlist_names(session: Session) -> set[str]:
    return {row[0] for row in session.execute(text("SELECT name FROM watchlists")).all()}


def test_tenant_a_sees_only_its_own_rows(two_tenants: dict[str, UUID]) -> None:
    # Act / Assert
    with session_scope(two_tenants["a"]) as session:
        assert _watchlist_names(session) == {"A-list"}


def test_tenant_b_sees_only_its_own_rows(two_tenants: dict[str, UUID]) -> None:
    with session_scope(two_tenants["b"]) as session:
        assert _watchlist_names(session) == {"B-list"}


def test_tenant_b_cannot_see_or_modify_tenant_a_rows(two_tenants: dict[str, UUID]) -> None:
    # From B's context, A's row is invisible AND unmodifiable (RLS hides it).
    with session_scope(two_tenants["b"]) as session:
        assert "A-list" not in _watchlist_names(session)
        updated = cast(
            "CursorResult[Any]",
            session.execute(text("UPDATE watchlists SET name = 'x' WHERE name = 'A-list'")),
        )
        deleted = cast(
            "CursorResult[Any]",
            session.execute(text("DELETE FROM watchlists WHERE name = 'A-list'")),
        )
        assert updated.rowcount == 0
        assert deleted.rowcount == 0

    # A's row is intact when viewed from A's own context.
    with session_scope(two_tenants["a"]) as session:
        assert _watchlist_names(session) == {"A-list"}


def test_no_tenant_context_denies_all_rows(two_tenants: dict[str, UUID]) -> None:
    # With no app.tenant_id bound, RLS denies every tenant-scoped row.
    with session_scope() as session:
        assert _watchlist_names(session) == set()

"""Cross-tenant RLS isolation for idempotency_keys (QV-052) — the mandatory denial gate
(project-context rule #2). Runs as the NON-superuser app role via ``session_scope``: tenant A's
idempotency record is invisible and immutable to tenant B, and an unbound session sees nothing.
This is why the same ``Idempotency-Key`` string is safe to reuse across tenants. Mirrors
``test_rls_portfolios.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CursorResult, Engine, text
from sqlalchemy.orm import Session

from quantvista.core.db import session_scope

pytestmark = pytest.mark.integration


@pytest.fixture
def world(admin_engine: Engine) -> Iterator[dict[str, UUID]]:
    a, b = uuid4(), uuid4()
    key = "shared-key"  # SAME key string for both tenants — proves per-tenant namespacing
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:a, 'IDEM-A'), (:b, 'IDEM-B')"),
            {"a": a, "b": b},
        )
        conn.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(tenant_id, idempotency_key, request_fingerprint, response_status, response_body) "
                "VALUES (:a, :k, 'fp-a', 201, '{\"t\":\"a\"}'::jsonb), "
                "(:b, :k, 'fp-b', 201, '{\"t\":\"b\"}'::jsonb)"
            ),
            {"a": a, "b": b, "k": key},
        )
    yield {"a": a, "b": b}
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), {"a": a, "b": b})


def _fingerprints(session: Session) -> set[str]:
    rows = session.execute(text("SELECT request_fingerprint FROM idempotency_keys")).all()
    return {r[0] for r in rows}


def test_each_tenant_sees_only_its_own_record(world: dict[str, UUID]) -> None:
    with session_scope(world["a"]) as session:
        assert _fingerprints(session) == {"fp-a"}
    with session_scope(world["b"]) as session:
        assert _fingerprints(session) == {"fp-b"}


def test_tenant_b_cannot_see_or_modify_tenant_a_record(world: dict[str, UUID]) -> None:
    with session_scope(world["b"]) as session:
        assert "fp-a" not in _fingerprints(session)
        updated = cast(
            "CursorResult[Any]",
            session.execute(
                text(
                    "UPDATE idempotency_keys SET response_status = 500 "
                    "WHERE request_fingerprint = 'fp-a'"
                )
            ),
        )
        deleted = cast(
            "CursorResult[Any]",
            session.execute(
                text("DELETE FROM idempotency_keys WHERE request_fingerprint = 'fp-a'")
            ),
        )
        assert updated.rowcount == 0
        assert deleted.rowcount == 0
    with session_scope(world["a"]) as session:  # A's record intact
        assert _fingerprints(session) == {"fp-a"}


def test_no_tenant_context_denies_all_rows(world: dict[str, UUID]) -> None:
    with session_scope() as session:
        assert _fingerprints(session) == set()

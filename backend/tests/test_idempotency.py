"""Unit tests for the idempotency module (api.idempotency, QV-052) — pure, no real DB.

Covers:
- ``fingerprint``: stability, key-order independence, body/path sensitivity, digest shape.
- ``idempotent``: concurrent-race ``IntegrityError`` branch (replay + conflict).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from quantvista.api.idempotency import IdempotencyConflict, fingerprint, idempotent


def test_same_request_same_fingerprint() -> None:
    a = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth", "benchmark": "NIFTY200_TRI"})
    b = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth", "benchmark": "NIFTY200_TRI"})
    assert a == b


def test_key_order_does_not_matter() -> None:
    a = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth", "benchmark": "NIFTY200_TRI"})
    b = fingerprint("POST", "/api/v1/portfolios", {"benchmark": "NIFTY200_TRI", "name": "Growth"})
    assert a == b


def test_different_body_differs() -> None:
    a = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth"})
    b = fingerprint("POST", "/api/v1/portfolios", {"name": "Value"})
    assert a != b


def test_different_path_differs() -> None:
    a = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth"})
    b = fingerprint("POST", "/api/v1/other", {"name": "Growth"})
    assert a != b


def test_fingerprint_is_hex_digest() -> None:
    fp = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth"})
    assert isinstance(fp, str) and len(fp) == 64  # sha-256 hex


# ---------------------------------------------------------------------------
# idempotent() — concurrent-race (IntegrityError) branch
# ---------------------------------------------------------------------------


def test_idempotent_concurrent_race_replays_winner() -> None:
    """Losing thread rolls back its failed INSERT and returns the winner's stored response."""
    session = MagicMock()
    tenant_id = uuid4()
    stored_body = {"status": "ok", "data": {"id": str(uuid4())}}
    fp = fingerprint("POST", "/api/v1/portfolios", {"name": "P1"})

    with (
        patch("quantvista.api.idempotency._lookup") as mock_lookup,
        patch("quantvista.api.idempotency._store") as mock_store,
    ):
        # First lookup: cache miss.  Second lookup (after rollback): winner's record.
        mock_lookup.side_effect = [None, (fp, 201, stored_body)]
        mock_store.side_effect = IntegrityError("UNIQUE", None, Exception("unique violation"))

        status, body = idempotent(
            session,
            tenant_id=tenant_id,
            key="race-key",
            method="POST",
            path="/api/v1/portfolios",
            body={"name": "P1"},
            produce=lambda: (201, stored_body),
        )

    assert status == 201
    assert body == stored_body
    session.rollback.assert_called_once()


def test_idempotent_concurrent_race_conflict_on_fingerprint_mismatch() -> None:
    """Same key but winner stored a different fingerprint → IdempotencyConflict (409)."""
    session = MagicMock()
    tenant_id = uuid4()
    fp_winner = fingerprint("POST", "/api/v1/portfolios", {"name": "P2"})

    with (
        patch("quantvista.api.idempotency._lookup") as mock_lookup,
        patch("quantvista.api.idempotency._store") as mock_store,
    ):
        mock_lookup.side_effect = [None, (fp_winner, 201, {})]
        mock_store.side_effect = IntegrityError("UNIQUE", None, Exception("unique violation"))

        with pytest.raises(IdempotencyConflict):
            idempotent(
                session,
                tenant_id=tenant_id,
                key="race-conflict-key",
                method="POST",
                path="/api/v1/portfolios",
                body={"name": "P1"},
                produce=lambda: (201, {}),
            )

    session.rollback.assert_called_once()

"""Idempotent-mutation helper (QV-052) — HTTP cross-cutting infra, beside ``pagination.py``.

Backs the ``Idempotency-Key`` header (04 §1): the first request for a key stores its
``(status, body)`` under ``(tenant_id, key)`` in ``idempotency_keys`` (RLS-scoped); a replay with
the *same* request returns it verbatim, and the same key with a *different* request body is a
client error (``IdempotencyConflict`` → 409). Reads/writes ride the caller's tenant session, so
RLS scopes them automatically. Generic on purpose — reusable by future mutations; wired only into
``POST /portfolios`` for now.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class IdempotencyConflict(Exception):
    """An ``Idempotency-Key`` was reused with a different request. → ``conflict`` (409)."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"idempotency key '{key}' was already used with a different request")


def fingerprint(method: str, path: str, body: dict[str, Any]) -> str:
    """Stable SHA-256 of the mutating request (method + path + canonical body).

    ``sort_keys`` makes it independent of body key order; ``default=str`` tolerates non-JSON scalars
    (e.g. ``Decimal``/``UUID``) that may appear in a normalized body.
    """
    canonical = json.dumps(
        {"method": method.upper(), "path": path, "body": body},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _lookup(session: Session, key: str) -> tuple[str, int, dict[str, Any]] | None:
    """Return ``(request_fingerprint, response_status, response_body)`` for the key, or ``None``.

    RLS scopes the read to the current tenant, so the key namespace is per-tenant automatically.
    """
    row = (
        session.execute(
            text(
                "SELECT request_fingerprint, response_status, response_body "
                "FROM idempotency_keys WHERE idempotency_key = :k"
            ),
            {"k": key},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return (row["request_fingerprint"], row["response_status"], row["response_body"])


def _store(
    session: Session,
    *,
    tenant_id: UUID,
    key: str,
    request_fingerprint: str,
    status: int,
    body: dict[str, Any],
) -> None:
    """Persist the first response for the key (``tenant_id`` set for the RLS ``WITH CHECK``)."""
    session.execute(
        text(
            "INSERT INTO idempotency_keys "
            "(tenant_id, idempotency_key, request_fingerprint, response_status, response_body) "
            "VALUES (:t, :k, :fp, :st, CAST(:body AS jsonb))"
        ),
        {
            "t": tenant_id,
            "k": key,
            "fp": request_fingerprint,
            "st": status,
            "body": json.dumps(body),
        },
    )


def idempotent(
    session: Session,
    *,
    tenant_id: UUID,
    key: str,
    method: str,
    path: str,
    body: dict[str, Any],
    produce: Callable[[], tuple[int, dict[str, Any]]],
) -> tuple[int, dict[str, Any]]:
    """Run ``produce`` at most once per ``(tenant, key)``; replay the stored result otherwise.

    - Cache hit + matching fingerprint → return the stored ``(status, body)`` (no re-execution).
    - Cache hit + different fingerprint → ``IdempotencyConflict`` (same key, different request).
    - Cache miss → execute ``produce()``, persist, return it. A concurrent create that loses the
      ``UNIQUE (tenant_id, idempotency_key)`` race is caught and resolved to a replay/conflict.
    """
    fp = fingerprint(method, path, body)

    existing = _lookup(session, key)
    if existing is not None:
        stored_fp, status, stored_body = existing
        if stored_fp != fp:
            raise IdempotencyConflict(key)
        return status, stored_body

    status, produced = produce()
    try:
        _store(
            session,
            tenant_id=tenant_id,
            key=key,
            request_fingerprint=fp,
            status=status,
            body=produced,
        )
    except IntegrityError:
        # Lost the unique race: another in-flight request stored first. Roll back our failed
        # INSERT and replay theirs (or 409 if it was a different request).
        session.rollback()
        winner = _lookup(session, key)
        if winner is None:  # pragma: no cover - the row must exist after a unique violation
            raise
        stored_fp, w_status, w_body = winner
        if stored_fp != fp:
            raise IdempotencyConflict(key) from None
        return w_status, w_body
    return status, produced
